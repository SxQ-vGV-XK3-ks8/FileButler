from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable, Iterable

CATEGORIES = {
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".heic", ".tif", ".tiff", ".raw"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".m4v"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".epub"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yml", ".yaml", ".toml", ".sql", ".java", ".cpp", ".cs", ".go", ".rs", ".php", ".sh"},
}

def category_for(path: Path) -> str:
    suffix = path.suffix.lower()
    for category, extensions in CATEGORIES.items():
        if suffix in extensions:
            return category
    return "Other"

def iter_files(folder: Path, recursive: bool = True) -> Iterable[Path]:
    """Walk directories without following symbolic links; skip inaccessible entries."""
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        yield Path(entry.path)
                    elif recursive and entry.is_dir(follow_symlinks=False):
                        yield from iter_files(Path(entry.path), True)
                except OSError:
                    continue
    except OSError:
        return

def sha256_file(path: Path, chunk_size: int = 1024 * 1024,
                cancel_check: Callable[[], bool] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            if cancel_check and cancel_check():
                raise InterruptedError("Duplicate scan cancelled.")
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()

def scan_folder(
    folder: Path,
    recursive: bool = True,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, Path], None] | None = None,
) -> list[dict]:
    folder = folder.expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"Folder does not exist: {folder}")
    results = []
    for index, path in enumerate(iter_files(folder, recursive), start=1):
        if cancel_check and cancel_check():
            break
        try:
            stat = path.stat(follow_symlinks=False)
            if not path.is_symlink() and path.is_file():
                results.append({
                    "path": path, "name": path.name, "suffix": path.suffix.lower(),
                    "category": category_for(path), "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
        except (PermissionError, OSError):
            continue
        if progress_callback:
            progress_callback(index, path)
    return results

def find_duplicates(files: list[dict],
                    cancel_check: Callable[[], bool] | None = None,
                    progress_callback: Callable[[int, Path], None] | None = None) -> dict[str, list[Path]]:
    """Hash only equal-sized files; returns duplicate content groups, never deletes files."""
    by_size: dict[int, list[Path]] = {}
    for item in files:
        by_size.setdefault(int(item["size"]), []).append(Path(item["path"]))
    duplicates: dict[str, list[Path]] = {}
    count = 0
    for paths in by_size.values():
        if len(paths) < 2:
            continue
        for path in paths:
            if cancel_check and cancel_check():
                return {digest: group for digest, group in duplicates.items() if len(group) > 1}
            try:
                digest = sha256_file(path, cancel_check=cancel_check)
                duplicates.setdefault(digest, []).append(path)
            except InterruptedError:
                return {digest: group for digest, group in duplicates.items() if len(group) > 1}
            except (PermissionError, OSError):
                continue
            count += 1
            if progress_callback:
                progress_callback(count, path)
    return {digest: paths for digest, paths in duplicates.items() if len(paths) > 1}
