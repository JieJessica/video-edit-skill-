#!/usr/bin/env python3
"""Create a 16:9 blurred-background highlight from a video."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Iterable


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def find_ffmpeg(explicit: str | None) -> str:
    candidates = []
    if explicit:
        candidates.append(explicit)
    env_path = os.environ.get("FFMPEG_EXE")
    if env_path:
        candidates.append(env_path)
    path_hit = shutil.which("ffmpeg")
    if path_hit:
        candidates.append(path_hit)

    try:
        import imageio_ffmpeg  # type: ignore

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
        if candidate and shutil.which(candidate):
            return candidate

    raise SystemExit(
        "ffmpeg not found. Install ffmpeg, set FFMPEG_EXE, install imageio-ffmpeg, "
        "or pass --ffmpeg <path>."
    )


def run_capture(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = proc.stdout.decode("utf-8", errors="replace")
    return proc.returncode, output


def parse_duration(ffmpeg: str, input_path: Path) -> float | None:
    code, output = run_capture([ffmpeg, "-hide_banner", "-i", str(input_path)])
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def mean_abs_diff(a: bytes, b: bytes) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def detect_highlight_start(
    ffmpeg: str,
    input_path: Path,
    duration: float,
    fps: int = 2,
    analysis_width: int = 160,
    analysis_height: int = 90,
) -> tuple[float, list[dict[str, float]]]:
    """Pick the highest-motion window using low-resolution frame differences."""
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        f"fps={fps},scale={analysis_width}:{analysis_height},format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    assert proc.stderr is not None

    frame_size = analysis_width * analysis_height
    previous = None
    samples: list[tuple[float, float]] = []
    frame_index = 0

    while True:
        frame = proc.stdout.read(frame_size)
        if not frame:
            break
        if len(frame) != frame_size:
            break
        timestamp = frame_index / fps
        if previous is not None:
            samples.append((timestamp, mean_abs_diff(frame, previous)))
        previous = frame
        frame_index += 1

    stderr = proc.stderr.read().decode("utf-8", errors="replace")
    code = proc.wait()
    if code != 0:
        raise SystemExit(stderr.strip() or "ffmpeg failed during highlight analysis.")
    if not samples:
        return 0.0, []

    source_duration = frame_index / fps
    clip_duration = min(duration, source_duration)
    max_start = max(0.0, source_duration - clip_duration)
    step = 0.5
    starts = [round(i * step, 3) for i in range(int(max_start / step) + 1)]
    scored = []

    for start in starts:
        end = start + clip_duration
        values = [score for timestamp, score in samples if start <= timestamp < end]
        score = sum(values) / max(1, len(values))
        scored.append((start, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    top: list[dict[str, float]] = []
    for start, score in scored:
        if all(abs(start - item["start"]) >= max(2.0, duration / 2) for item in top):
            top.append({"start": start, "end": start + clip_duration, "score": round(score, 4)})
        if len(top) == 5:
            break

    return (scored[0][0] if scored else 0.0), top


def parse_resolution(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", value.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError("Resolution must look like 1920x1080.")
    width, height = int(match.group(1)), int(match.group(2))
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Resolution dimensions must be positive.")
    if abs((width / height) - (16 / 9)) > 0.01:
        raise argparse.ArgumentTypeError("Resolution must be approximately 16:9.")
    if width % 2 or height % 2:
        raise argparse.ArgumentTypeError("Resolution dimensions must be even.")
    return width, height


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_16x9_highlight.mp4")


def build_filter(width: int, height: int, blur: float) -> str:
    return (
        "[0:v]split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={blur},setsar=1[bg];"
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
    )


def create_video(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    start: float,
    duration: float,
    width: int,
    height: int,
    blur: float,
    include_audio: bool,
    crf: int,
    preset: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(input_path),
        "-filter_complex",
        build_filter(width, height, blur),
        "-map",
        "[v]",
    ]
    if include_audio:
        cmd.extend(["-map", "0:a?"])
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-preset",
            preset,
        ]
    )
    if include_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "160k", "-shortest"])
    cmd.extend(["-movflags", "+faststart", str(output_path)])

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "ffmpeg failed during render.")


def file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Input video path.")
    parser.add_argument("--output", help="Output MP4 path.")
    parser.add_argument("--ffmpeg", help="Path to ffmpeg executable.")
    parser.add_argument("--start", type=float, help="Manual highlight start in seconds.")
    parser.add_argument("--duration", type=float, default=10.0, help="Clip duration in seconds.")
    parser.add_argument(
        "--auto-highlight",
        action="store_true",
        help="Detect the highest-motion window. Used automatically when --start is omitted.",
    )
    parser.add_argument("--resolution", type=parse_resolution, default=(1920, 1080))
    parser.add_argument("--blur", type=float, default=30.0, help="Gaussian blur sigma.")
    parser.add_argument("--mute", action="store_true", help="Do not include audio.")
    parser.add_argument("--crf", type=int, default=18, help="x264 quality; lower is better.")
    parser.add_argument("--preset", default="medium", help="x264 preset.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input video not found: {input_path}")
    output_path = Path(args.output).expanduser().resolve() if args.output else default_output_path(input_path)

    ffmpeg = find_ffmpeg(args.ffmpeg)
    source_duration = parse_duration(ffmpeg, input_path)
    requested_duration = max(0.1, float(args.duration))
    render_duration = min(requested_duration, source_duration) if source_duration else requested_duration

    candidates: list[dict[str, float]] = []
    if args.start is None:
        start, candidates = detect_highlight_start(ffmpeg, input_path, render_duration)
    else:
        start = max(0.0, float(args.start))
        if source_duration:
            start = min(start, max(0.0, source_duration - render_duration))

    width, height = args.resolution
    create_video(
        ffmpeg=ffmpeg,
        input_path=input_path,
        output_path=output_path,
        start=start,
        duration=render_duration,
        width=width,
        height=height,
        blur=float(args.blur),
        include_audio=not args.mute,
        crf=int(args.crf),
        preset=str(args.preset),
    )

    summary = {
        "input": str(input_path),
        "output": str(output_path),
        "start_seconds": round(start, 3),
        "end_seconds": round(start + render_duration, 3),
        "duration_seconds": round(render_duration, 3),
        "resolution": f"{width}x{height}",
        "audio_preserved": not args.mute,
        "bytes": file_size(output_path),
        "auto_highlight_candidates": candidates,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Created {output_path}")
        print(f"Highlight: {summary['start_seconds']}s to {summary['end_seconds']}s")
        print(f"Resolution: {summary['resolution']}; audio preserved: {summary['audio_preserved']}")
        print(f"Size: {summary['bytes']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
