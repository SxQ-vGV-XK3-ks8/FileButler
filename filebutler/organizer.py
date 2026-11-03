from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable

from .rules import config_directory, load_rules
from .scanner import category_for

def unique_destination(destination: Path) -> Path:
    """Return a non-existing destination path without overwriting anything."""
    if not destination.exists():
        return destination
    stem, suffix = destination.stem, destination.suffix
    counter = 1
    while True:
        candidate = destination.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
        counter += 1

def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()

def history_path(root: Path) -> Path:
    """Keep operation history outside the folders being organized."""
    identity = hashlib.sha256(str(root.expanduser().resolve()).encode("utf-8")).hexdigest()[:20]
    return config_directory() / f"history-{identity}.json"

def _read_history(path: Path) -> dict:
    if not path.exists():
        return {"operations": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("operations"), list):
        raise ValueError("The FileButler history file has an invalid format.")
    for operation in data["operations"]:
        if not isinstance(operation, dict) or not isinstance(operation.get("moves", []), list):
            raise ValueError("The FileButler history file contains an invalid operation.")
        for move in operation.get("moves", []):
            if not isinstance(move, dict) or not all(isinstance(move.get(k), str) for k in ("source", "destination", "sha256")):
                raise ValueError("The FileButler history file contains an invalid move record.")
    return data

def _write_history(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the target, flush it, then atomically replace the previous journal.
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise

def build_sort_plan(files: list[dict], root: Path, rules: dict[str, str] | None = None) -> list[tuple[Path, Path]]:
    root = root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Selected root is not a directory: {root}")
    rules = rules if rules is not None else load_rules()
    plan = []
    reserved: set[Path] = set()
    for item in files:
        raw_source = Path(item["path"]).expanduser()
        # Do not resolve symlinks into targets: symlink inputs are never eligible for moves.
        if raw_source.is_symlink():
            continue
        source: Path = raw_source.resolve()
        # Never allow a caller-provided scan result to move a file outside the chosen root.
        try:
            source.relative_to(root)
        except ValueError:
            continue
        if not source.is_file():
            continue
        category = rules.get(source.suffix.lower(), category_for(source))
        if source.parent == root / category:
            continue
        destination = root / category / source.name
        # Defend against malformed rules or unexpected path composition.
        try:
            destination.parent.resolve().relative_to(root)
        except ValueError:
            continue
        candidate = destination
        counter = 1
        while candidate.exists() or candidate in reserved:
            candidate = destination.with_name(f"{destination.stem} ({counter}){destination.suffix}")
            counter += 1
        reserved.add(candidate)
        plan.append((source, candidate))
    return plan

def apply_sort_plan(
    plan: list[tuple[Path, Path]],
    history_file: Path | None = None,
) -> list[tuple[Path, Path]]:
    """Move files and persist a recoverable operation log after every successful move."""
    completed: list[tuple[Path, Path]] = []
    if not plan:
        return completed

    normalized = []
    roots = set()
    for raw_source, raw_destination in plan:
        source = Path(raw_source).expanduser()
        destination = Path(raw_destination).expanduser()
        if source.is_symlink() or destination.is_symlink():
            raise ValueError("Sorting plans cannot contain symbolic links.")
        source = source.resolve()
        destination_parent = destination.parent.resolve()
        destination = destination_parent / destination.name
        roots.add(destination_parent.parent)
        if not source.is_file():
            raise FileNotFoundError(f"Source file is missing: {source}")
        if source == destination:
            raise ValueError("Source and destination are identical.")
        normalized.append((source, destination))
    if len(roots) != 1:
        raise ValueError("A sorting operation must target one selected folder.")
    root = next(iter(roots)).resolve()
    for source, destination in normalized:
        try:
            source.relative_to(root)
            destination.relative_to(root)
        except ValueError as error:
            raise ValueError("Sorting plans cannot move files outside the selected folder.") from error
    if len({destination for _, destination in normalized}) != len(normalized):
        raise ValueError("Sorting plan contains destination collisions.")
    plan = normalized

    if history_file is None:
        # Derive history from the common destination root.
        roots = {destination.parent.parent.resolve() for _, destination in plan}
        if len(roots) != 1:
            raise ValueError("A sorting operation must target one selected folder.")
        history_file = history_path(next(iter(roots)))

    history = _read_history(history_file)
    operation = {"moves": [], "state": "in_progress"}
    history["operations"].append(operation)
    _write_history(history_file, history)

    try:
        for source, destination in plan:
            source = source.resolve()
            if not source.is_file():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            safe_destination = unique_destination(destination)
            # Check immediately before moving. Existing destinations are never intentionally overwritten.
            if safe_destination.exists():
                safe_destination = unique_destination(safe_destination)
            digest = file_sha256(source)
            shutil.move(str(source), str(safe_destination))
            if not safe_destination.is_file() or file_sha256(safe_destination) != digest:
                # Preserve the moved file and record an incomplete operation for recovery.
                move_record = {
                    "source": str(source), "destination": str(safe_destination),
                    "sha256": digest, "undone": False,
                }
                operation["moves"].append(move_record)
                completed.append((source, safe_destination))
                _write_history(history_file, history)
                raise OSError(f"File verification failed after moving: {safe_destination}")
            move_record = {
                "source": str(source),
                "destination": str(safe_destination),
                "sha256": digest,
                "undone": False,
            }
            operation["moves"].append(move_record)
            completed.append((source, safe_destination))
            _write_history(history_file, history)
        operation["state"] = "completed"
        _write_history(history_file, history)
    except Exception:
        operation["state"] = "partial"
        _write_history(history_file, history)
        raise
    return completed

def undo_last_sort(root: Path, history_file: Path | None = None) -> list[tuple[Path, Path]]:
    """Undo the newest operation with completed moves, refusing ambiguous or unsafe restores."""
    root = root.expanduser().resolve()
    history_file = history_file or history_path(root)
    history = _read_history(history_file)

    operation = next(
        (item for item in reversed(history["operations"])
         if item.get("state") in {"completed", "partial"} and any(not m.get("undone", False) for m in item.get("moves", []))),
        None,
    )
    if operation is None:
        return []

    restored = []
    # Validate and restore one move at a time, newest first.
    for move in reversed(operation["moves"]):
        if move.get("undone"):
            continue
        source = Path(move["source"]).expanduser()
        destination = Path(move["destination"]).expanduser()
        # A damaged or hand-edited journal must not be able to move files outside
        # the folder whose history is being undone.
        try:
            source.resolve().relative_to(root)
            destination.resolve().relative_to(root)
        except ValueError as error:
            raise ValueError("Cannot undo: history contains a path outside the selected folder.") from error
        if source.is_symlink() or destination.is_symlink():
            raise ValueError("Cannot undo: symbolic links are not restored automatically.")

        if not destination.is_file():
            raise FileNotFoundError(f"Cannot undo: moved file is missing: {destination}")
        if source.exists():
            raise FileExistsError(f"Cannot undo without overwriting an existing file: {source}")
        if file_sha256(destination) != move["sha256"]:
            raise ValueError(f"Cannot undo: file contents changed since sorting: {destination}")

        source.parent.mkdir(parents=True, exist_ok=True)
        # Re-check immediately before moving to reduce race-condition risk.
        if source.exists():
            raise FileExistsError(f"Cannot undo without overwriting an existing file: {source}")
        shutil.move(str(destination), str(source))
        move["undone"] = True
        restored.append((destination, source))
        _write_history(history_file, history)

    operation["state"] = "undone"
    _write_history(history_file, history)
    return restored

def has_undo(root: Path, history_file: Path | None = None) -> bool:
    try:
        history = _read_history(history_file or history_path(root))
        return any(
            item.get("state") in {"completed", "partial"}
            and any(not move.get("undone", False) for move in item.get("moves", []))
            for item in history["operations"]
        )
    except (OSError, json.JSONDecodeError, ValueError):
        return False
