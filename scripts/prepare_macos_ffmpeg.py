#!/usr/bin/env python3
"""Stage a self-contained FFmpeg binary for the macOS application bundle."""

from __future__ import annotations

import shutil
from pathlib import Path


def main() -> None:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise SystemExit("Install imageio-ffmpeg before building the macOS desktop application") from exc

    output_dir = Path("build/ffmpeg-runtime")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    destination = output_dir / "ffmpeg"
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), destination)
    destination.chmod(0o755)
    print(f"Prepared self-contained FFmpeg runtime at {output_dir}")


if __name__ == "__main__":
    main()
