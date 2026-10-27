"""Fetch the ANDES documentation sources for one release tag into a local cache.

Downloads the GitHub source archive of ``CURENT/andes`` at ``--tag``, extracts
only ``docs/source/`` and ``LICENSE``, converts every Jupyter notebook to a
plain Markdown file (code and markdown cells, no outputs) under ``text/`` so it
can be searched and read cheaply, and writes ``SOURCE.json`` with the tag, the
resolved commit, the archive URL and its SHA-256.

Standard library only. Nothing from the archive is executed.

    python fetch_andes_docs.py                      # v2.0.0 -> default cache folder (see below)
    python fetch_andes_docs.py --tag v2.0.0 --dest /data/andes-docs --force

Default destination: $ANDES_DOCS_DIR if set, else ~/.claude/skills-cache/andes-docs-<tag>.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REPO = "CURENT/andes"
DEFAULT_TAG = "v2.0.0"
EXPECTED_V2_COMMIT = "eda5163c9ee8"  # commit the skill was verified against
USER_AGENT = "andes-agent-skill"


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def resolve_commit(tag: str) -> str | None:
    try:
        data = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{tag}"))
        return str(data["sha"])
    except Exception:  # rate limit or offline: the archive SHA-256 still pins the content
        return None


def notebook_to_markdown(notebook: dict, title: str) -> str:
    """Render code and markdown cells of a notebook as Markdown, dropping outputs."""
    parts = [f"<!-- converted from {title}; outputs omitted -->\n"]
    for cell in notebook.get("cells", []):
        source = cell.get("source", "")
        text = "".join(source) if isinstance(source, list) else str(source)
        if not text.strip():
            continue
        if cell.get("cell_type") == "code":
            parts.append(f"```python\n{text.rstrip()}\n```\n")
        else:
            parts.append(text.rstrip() + "\n")
    return "\n".join(parts)


def _safe_member_path(name: str, prefix: str) -> PurePosixPath | None:
    """Path of an archive member relative to ``prefix``, or None if outside/unsafe."""
    if "\\" in name:  # backslash is a path separator on Windows: reject, never reinterpret
        return None
    path = PurePosixPath(name)
    parts = path.parts
    if len(parts) < 2 or ".." in parts or path.is_absolute():
        return None
    relative = PurePosixPath(*parts[1:])  # drop the "andes-<tag>/" root folder
    if relative.as_posix() == "LICENSE":
        return relative
    if relative.as_posix().startswith(prefix):
        return relative
    return None


def fetch(tag: str, dest: Path, force: bool) -> dict:
    dest = dest.expanduser().resolve()
    if dest == Path(dest.anchor) or dest in {Path.home().resolve(), Path.cwd().resolve()}:
        raise SystemExit(f"Refusing unsafe destination: {dest}")
    if dest.exists() and any(dest.iterdir()):
        if not force:
            raise SystemExit(f"Destination is not empty: {dest} (use --force to replace it)")
        if not (dest / "SOURCE.json").is_file():
            raise SystemExit(f"Refusing to replace {dest}: it is not a docs cache (no SOURCE.json)")
        shutil.rmtree(dest)

    url = f"https://codeload.github.com/{REPO}/tar.gz/refs/tags/{tag}"
    archive = _get(url)
    digest = hashlib.sha256(archive).hexdigest()
    commit = resolve_commit(tag)
    if tag == DEFAULT_TAG and commit is not None and not commit.startswith(EXPECTED_V2_COMMIT):
        print(
            f"WARNING: tag {tag} now resolves to commit {commit[:12]}, not the verified {EXPECTED_V2_COMMIT}; "
            "the upstream tag moved. Treat the docs as unverified.",
            file=sys.stderr,
        )

    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            relative = _safe_member_path(member.name, "docs/source/")
            if relative is None:
                continue
            target = dest / Path(*relative.parts)
            if not target.resolve().is_relative_to(dest):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = tar.extractfile(member).read()
            target.write_bytes(payload)
            written += 1
            if relative.suffix == ".ipynb":
                text_target = dest / "text" / Path(*relative.parts).with_suffix(".md")
                if not text_target.resolve().is_relative_to(dest):
                    continue
                text_target.parent.mkdir(parents=True, exist_ok=True)
                notebook = json.loads(payload.decode("utf-8"))
                text_target.write_text(notebook_to_markdown(notebook, relative.as_posix()), encoding="utf-8")

    record = {
        "repo": f"https://github.com/{REPO}",
        "tag": tag,
        "commit": commit,
        "archive_url": url,
        "archive_sha256": digest,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "files_extracted": written,
        "license": "GPL-3.0 (see LICENSE); local reference copy, not redistributed with the skill",
    }
    (dest / "SOURCE.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def default_dest(tag: str) -> Path:
    """$ANDES_DOCS_DIR when set, otherwise ~/.claude/skills-cache/andes-docs-<tag>."""
    override = os.environ.get("ANDES_DOCS_DIR")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "skills-cache" / f"andes-docs-{tag}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument("--dest", default=None, help="default: $ANDES_DOCS_DIR or ~/.claude/skills-cache/andes-docs-<tag>")
    parser.add_argument("--force", action="store_true", help="replace an existing docs cache")
    args = parser.parse_args(argv)
    dest = Path(args.dest) if args.dest else default_dest(args.tag)
    record = fetch(args.tag, dest, args.force)
    print(json.dumps({"dest": str(dest.expanduser().resolve()), **record}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
