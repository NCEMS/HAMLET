"""Apply nested Peptonizer patches and install it into the invoking environment."""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def install(submodule):
    root = Path(submodule).resolve()
    checkout = root / "submodules/peptonizer2000"
    order = ("pandas_compat.patch", "unipept_nontryptic_species_rollup.patch", "pride_genus_rollup.patch")
    patches = [root / "patches/peptonizer2000" / name for name in order]
    # Build desired files from the pinned commit, so repeated installation remains
    # safe even when later patches change earlier patches' context.
    with tempfile.TemporaryDirectory() as directory:
        desired = Path(directory)
        touched = set()
        for patch in patches:
            for line in patch.read_text().splitlines():
                if line.startswith("+++ b/"):
                    touched.add(line[6:])
        for name in touched:
            content = subprocess.check_output(
                ["git", "-C", str(checkout), "show", "HEAD:" + name])
            path = desired / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        for patch in patches:
            subprocess.run(["git", "apply", str(patch)], cwd=desired, check=True)
        for name in touched:
            current = (checkout / name).read_bytes()
            wanted = (desired / name).read_bytes()
            original = subprocess.check_output(
                ["git", "-C", str(checkout), "show", "HEAD:" + name])
            if current not in (wanted, original):
                raise RuntimeError(f"Conflicting local dependency modifications: {checkout / name}")
        for name in touched:
            (checkout / name).write_bytes((desired / name).read_bytes())
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "-e", str(checkout / "peptonizer")],
        check=True,
    )
    print(f"Installed patched Peptonizer from {checkout}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submodule", required=True)
    install(parser.parse_args().submodule)
