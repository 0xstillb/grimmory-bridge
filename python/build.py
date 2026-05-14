from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SUPPORTED_TRIPLES = {
    "x86_64-pc-windows-msvc",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
}


def _host_triple() -> str:
    out = subprocess.run(
        ["rustc", "-vV"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("Could not determine rust host triple from `rustc -vV`")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Grimmory Bridge Python sidecar with PyInstaller.")
    parser.add_argument(
        "--triple",
        default="host",
        help="Output target triple name. Use 'host' (default) or one of supported triples.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    python_root = repo_root / "python"
    binaries_dir = repo_root / "src-tauri" / "binaries"
    build_dir = python_root / ".build"
    spec_dir = python_root / ".spec"

    binaries_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    host_triple = _host_triple()
    triple = host_triple if args.triple == "host" else str(args.triple).strip()
    if triple not in SUPPORTED_TRIPLES:
        raise RuntimeError(
            f"Unsupported triple '{triple}'. Supported: {', '.join(sorted(SUPPORTED_TRIPLES))}"
        )

    if triple != host_triple:
        print(
            f"Warning: host triple is '{host_triple}' but output is named as '{triple}'. "
            "PyInstaller does not cross-compile; run this script on the matching host OS/arch."
        )

    name = f"grimmory-bridge-py-{triple}"
    if triple.endswith("windows-msvc"):
        name += ".exe"

    entrypoint = python_root / "grimmory_bridge" / "rpc.py"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        name,
        "--paths",
        str(repo_root),
        "--distpath",
        str(binaries_dir),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(spec_dir),
        str(entrypoint),
    ]

    print("Building Python sidecar:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print("Done:", binaries_dir / name)


if __name__ == "__main__":
    main()
