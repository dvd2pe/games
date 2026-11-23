#!/usr/bin/env python3
"""Extract ZIPs safely to sibling folders without replacing existing files."""
import hashlib
import json
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 75000
MAX_TOTAL = 3 * 1024**3
MAX_MEMBER = 95 * 1024**2


def unpack(source):
    output = source.with_suffix("")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = output / ".zip-extract-manifest.json"
    if output.exists() or output.is_symlink():
        if output.is_dir() and not output.is_symlink() and manifest.is_file():
            try:
                if json.loads(manifest.read_text()).get("sha256") == sha:
                    print(f"Unchanged: {source.relative_to(ROOT)}")
                    return
            except (ValueError, OSError):
                pass
        raise ValueError(f"Output exists; refusing to overwrite: {output}")
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_TOTAL:
            raise ValueError(f"Archive too large: {source}")
        targets = []
        used = set()
        for member in members:
            name = member.filename.replace("\\", "/")
            parts = name.split("/")
            path = PurePosixPath(name)
            mode = stat.S_IFMT(member.external_attr >> 16)
            if (name.startswith("/") or ":" in name or
                any(p in ("..", ".") for p in parts) or not path.parts or
                path.as_posix() == ".zip-extract-manifest.json" or
                mode not in (0, stat.S_IFREG, stat.S_IFDIR) or
                member.flag_bits & 1 or member.file_size > MAX_MEMBER):
                raise ValueError(f"Unsafe ZIP member: {name!r}")
            if path in used:
                raise ValueError(f"Duplicate ZIP member: {name!r}")
            used.add(path)
            targets.append((member, path))
        with tempfile.TemporaryDirectory(prefix=".zip-work-", dir=source.parent) as tmp:
            stage = Path(tmp) / "payload"
            stage.mkdir()
            for member, path in targets:
                target = stage.joinpath(*path.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as inp, target.open("xb") as out:
                        import shutil
                        shutil.copyfileobj(inp, out, 1024 * 1024)
            (stage / ".zip-extract-manifest.json").write_text(
                json.dumps({"archive": str(source.relative_to(ROOT)), "sha256": sha}) + "\n"
            )
            stage.rename(output)
        print(f"Extracted: {source.relative_to(ROOT)}")


def main():
    done = set()
    for _ in range(3):
        pending = sorted(p for p in ROOT.rglob("*")
                         if p.is_file() and p.suffix.lower() == ".zip"
                         and ".git" not in p.relative_to(ROOT).parts
                         and not any(part.startswith(".zip-work-")
                                     for part in p.relative_to(ROOT).parts)
                         and p not in done)
        for source in pending:
            done.add(source)
            unpack(source)
    print("Extraction complete")


if __name__ == "__main__":
    main()
