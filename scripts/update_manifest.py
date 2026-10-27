"""Regenerate MANIFEST.json (path, size and SHA-256 of every skill file).

Run from anywhere after changing the skill:  python scripts/update_manifest.py
Metadata fields already in MANIFEST.json (versions, validation summary) are kept.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "_smoke", "runs", "results"}


def list_files() -> list[Path]:
    """Tracked files when ROOT is a git repo (staged files count); otherwise a filtered walk."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            capture_output=True, check=True, timeout=30,
        ).stdout.decode("utf-8")
        toplevel = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
            capture_output=True, check=True, timeout=30,
        ).stdout.decode("utf-8").strip()
        if Path(toplevel).resolve() == ROOT:
            return sorted(ROOT / name for name in out.split(chr(0)) if name and (ROOT / name).is_file())
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        pass
    return sorted(
        path for path in ROOT.rglob("*")
        if path.is_file() and not SKIP_DIRS.intersection(path.relative_to(ROOT).parts)
    )


def main() -> int:
    manifest_path = ROOT / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    files = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in list_files()
        if path.name != "MANIFEST.json"
    ]
    manifest.update(
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        file_count_excluding_manifest=len(files),
        files=files,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"MANIFEST.json: {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
