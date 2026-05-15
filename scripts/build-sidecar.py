#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PyInstaller sidecar for a target triple.")
    parser.add_argument("--triple", required=True, help="Rust target triple, e.g. x86_64-pc-windows-msvc")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    entry = repo / "python" / "grimmory_bridge" / "rpc.py"
    dist = repo / "dist"
    build = repo / "build"
    spec = repo / "grimmory-bridge-py.spec"
    out_dir = repo / "src-tauri" / "binaries"
    out_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "grimmory-bridge-py",
            str(entry),
        ],
        repo,
    )

    src = dist / "grimmory-bridge-py"
    ext = ".exe" if args.triple.endswith("windows-msvc") else ""
    if ext:
        src = src.with_suffix(ext)

    if not src.exists():
        raise FileNotFoundError(f"PyInstaller output not found: {src}")

    dst = out_dir / f"grimmory-bridge-py-{args.triple}{ext}"
    shutil.copy2(src, dst)
    print(f"Built sidecar: {dst}")

    # Keep workspace clean in CI and local runs.
    if build.exists():
        shutil.rmtree(build, ignore_errors=True)
    if dist.exists():
        shutil.rmtree(dist, ignore_errors=True)
    if spec.exists():
        spec.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
