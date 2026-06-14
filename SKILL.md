---
name: make-widescreen-highlight
description: Convert vertical or non-16:9 videos into 16:9 widescreen highlight clips with a blurred full-frame background and the original video centered on top. Use when the user asks to make a video widescreen, add a blurred background, keep the original clip centered, preserve audio, extract a 10-second highlight, create social-media landscape output, or process MP4/MOV video files from Downloads or another local folder.
---

# Make Widescreen Highlight

## Overview

Create a 16:9 video clip by blurring and cropping a scaled copy of the source video as the background, then overlaying the original video centered and unblurred. Default to a 10-second highlight when the user asks for a highlight and gives no exact timestamp.

Use `scripts/make_widescreen_highlight.py` for the actual processing. It wraps ffmpeg, preserves audio by default, can auto-detect a motion-heavy highlight window, and handles paths with spaces or non-English characters.

## Workflow

1. Find the input video:
   - If the user names a file and folder, search that folder first.
   - If the user says "Downloads" or "Download", search the user's Downloads directory.
   - Match partial names when needed, then confirm only if multiple plausible files remain.

2. Decide the highlight window:
   - Use the user's exact start/end or start/duration when provided.
   - If no timestamp is provided, use `--auto-highlight` and default `--duration 10`.
   - If the user says "highlight" but also specifies a timestamp, prefer the timestamp.

3. Generate the widescreen output:
   - Default resolution: `1920x1080`.
   - Default aspect ratio: `16:9`.
   - Background: scaled to fill, cropped, and blurred.
   - Foreground: original video scaled to fit inside the frame, centered, not blurred.
   - Audio: preserve original audio unless the user asks to mute.

4. Verify output:
   - Confirm the output file exists and has nonzero size.
   - Probe or inspect ffmpeg output to ensure the final dimensions are 16:9.
   - Report the output path, selected highlight start/end, and whether audio was preserved.

## Script Usage

Basic:

```powershell
python scripts/make_widescreen_highlight.py --input "C:\path\video.mp4" --output "C:\path\video_widescreen_highlight.mp4"
```

Common options:

```powershell
python scripts/make_widescreen_highlight.py `
  --input "C:\path\video.mp4" `
  --output "C:\path\video_16x9_highlight.mp4" `
  --auto-highlight `
  --duration 10 `
  --resolution 1920x1080 `
  --blur 30
```

Manual timestamp:

```powershell
python scripts/make_widescreen_highlight.py --input "C:\path\video.mp4" --start 24 --duration 10
```

If ffmpeg is not on `PATH`, install or locate one and pass `--ffmpeg <path>`. In Codex desktop environments, `imageio-ffmpeg` can be installed into a temporary directory and the script can use it when that package is importable.

## Output Naming

When the user does not specify an output path, place the rendered file next to the input using:

```text
<original-stem>_16x9_highlight.mp4
```

For workspace-deliverable outputs, use a clear path under the current workspace's `outputs/` directory.

## Quality Notes

Prefer `1920x1080` for final delivery unless the input is tiny or the user asks for a smaller file. Use `1280x720` for quick previews.

If auto-highlight selects an obviously bad segment, such as black frames, a title card, or dead air, inspect a thumbnail sheet and rerun with `--start`.
