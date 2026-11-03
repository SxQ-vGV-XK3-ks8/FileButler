from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_RULES = {
    ".png": "Images", ".jpg": "Images", ".jpeg": "Images", ".gif": "Images",
    ".bmp": "Images", ".webp": "Images", ".svg": "Images", ".heic": "Images",
    ".mp4": "Videos", ".mkv": "Videos", ".mov": "Videos", ".avi": "Videos", ".webm": "Videos",
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio", ".aac": "Audio", ".ogg": "Audio", ".m4a": "Audio",
    ".pdf": "Documents", ".doc": "Documents", ".docx": "Documents", ".odt": "Documents",
    ".rtf": "Documents", ".txt": "Documents", ".md": "Documents", ".xls": "Documents",
    ".xlsx": "Documents", ".ppt": "Documents", ".pptx": "Documents", ".csv": "Documents",
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives", ".tar": "Archives", ".gz": "Archives",
    ".py": "Code", ".js": "Code", ".ts": "Code", ".html": "Code", ".css": "Code",
    ".json": "Code", ".xml": "Code", ".yml": "Code", ".yaml": "Code", ".toml": "Code",
    ".sql": "Code", ".java": "Code", ".cpp": "Code", ".cs": "Code",
}

def config_directory() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.environ.get("XDG_CONFIG_HOME"):
        base = Path(os.environ["XDG_CONFIG_HOME"])
    else:
        base = Path.home() / ".config"
    path = base / "FileButler"
    path.mkdir(parents=True, exist_ok=True)
    return path

def rules_path() -> Path:
    return config_directory() / "rules.json"

def load_rules() -> dict[str, str]:
    path = rules_path()
    if not path.exists():
        return dict(DEFAULT_RULES)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate_rules(data)
    except (OSError, json.JSONDecodeError, ValueError):
        return dict(DEFAULT_RULES)

def validate_rules(data: object) -> dict[str, str]:
    if not isinstance(data, dict):
        raise ValueError("Rules must be a JSON object mapping extensions to folder names.")
    result = {}
    for extension, category in data.items():
        if not isinstance(extension, str) or not extension.startswith(".") or len(extension) < 2:
            raise ValueError(f"Invalid extension: {extension!r}. Use values such as .pdf.")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"Invalid category for {extension}.")
        category = category.strip()
        if category in {".", ".."} or any(char in category for char in r'\/:*?"<>|'):
            raise ValueError(f"Invalid folder name for {extension}: {category!r}.")
        result[extension.lower()] = category
    return result

def save_rules(data: object) -> dict[str, str]:
    rules = validate_rules(data)
    target = rules_path()
    import tempfile
    fd, temporary_name = tempfile.mkstemp(prefix="rules.json.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(rules, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return rules
