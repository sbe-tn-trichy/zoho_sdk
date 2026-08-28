import os
import re
from pathlib import Path
from typing import Optional

_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: Optional[str], fallback: str = "unnamed") -> str:
    """
    Sanitize an untrusted filename to prevent path traversal and invalid filesystem characters.
    Extracts the basename and strips dangerous characters.
    """
    if not name:
        return fallback

    # Extract base filename to neutralize path traversal sequences (e.g., ../ or C:\)
    candidate = os.path.basename(str(name).strip())
    # Strip dangerous/invalid characters
    candidate = _UNSAFE_FILENAME_CHARS.sub("_", candidate)
    # Strip trailing spaces or dots (problematic on Windows/POSIX)
    candidate = candidate.rstrip(" .")
    
    # Avoid reserved or empty names
    if candidate in {"", ".", "..", "..."}:
        return fallback
    return candidate


def resolve_output_path(save_path: str, base_dir: str = "output") -> str:
    """
    Safely resolve an output file path.
    If save_path is relative, confines it inside base_dir, preventing directory traversal.
    """
    base_path = Path(base_dir).expanduser().resolve()
    target_path = Path(save_path).expanduser()

    if not target_path.is_absolute():
        # If relative, anchor to base_dir
        resolved = (base_path / target_path).resolve()
    else:
        resolved = target_path.resolve()

    # If the path was relative, verify it has not escaped base_dir
    if not target_path.is_absolute():
        try:
            resolved.relative_to(base_path)
        except ValueError:
            # Traversal attempted; sanitize target name within base_dir
            safe_name = sanitize_filename(target_path.name)
            resolved = base_path / safe_name

    return str(resolved)
