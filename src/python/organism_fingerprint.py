"""Fingerprint organism-ID code, reference inputs, and execution settings."""

import argparse
import hashlib
import json
from pathlib import Path


def fingerprint(submodule, files, settings, assets=()):
    root = Path(submodule)
    code = [root / "src" / name for name in
            ("OrganismID.py", "cascadia_wrapper.py", "PipelineLogger.py")]
    code.extend(sorted((root / "patches/peptonizer2000").glob("*.patch")))
    code.extend(sorted((root / "submodules/peptonizer2000/peptonizer/peptonizer").glob("*.py")))
    digest = hashlib.sha256(settings.encode())
    references = []
    for entry in files:
        path = Path(entry)
        if path.is_dir():
            references.extend(sorted(child for child in path.rglob("*") if child.is_file()))
        else:
            references.append(path)
    for path in code + references:
        digest.update(path.name.encode())
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    for entry in assets:
        path = Path(entry)
        digest.update(str(path.resolve()).encode())
        if path.is_file():
            stat = path.stat()
            digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
        else:
            digest.update(b"missing")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submodule", required=True)
    parser.add_argument("--files", nargs="+", required=True)
    parser.add_argument("--settings", required=True)
    parser.add_argument("--assets", nargs="*", default=[])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--pxd", required=True)
    args = parser.parse_args()
    with open(args.manifest) as handle:
        manifest = json.load(handle)
    if not manifest["pxds"][args.pxd]["stages"]["organism_id"]["availability"]:
        print("disabled")
        return
    print(fingerprint(args.submodule, args.files, args.settings, args.assets))


if __name__ == "__main__":
    main()
