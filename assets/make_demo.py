#!/usr/bin/env python3
"""Turns a screen recording into the README demo: a light GIF that GitHub plays inline, an MP4 for
posts, and a still for the first frame.

    python assets/make_demo.py recording.mp4
    python assets/make_demo.py recording.mp4 --keep 0:03-0:09@3 --keep 0:41-0:55 --crop 0,80,1600,900
    python assets/make_demo.py recording.mp4 --keep 0:41-0:55 --width 880 --fps 10 --hold 2

--keep START-END[@SPEED]   a piece to keep, in order; @3 plays it three times faster. Repeat it to
                           cut the waiting out. Without --keep the whole recording is used.
--crop X,Y,W,H             the part of the screen to keep, in pixels of the recording (cut the
                           sidebar, the taskbar, anything personal).
--width                    width of the GIF (default 960; the MP4 is 1280 or the crop's width).
--fps                      frames per second of the GIF (default 12).
--hold                     seconds to hold the last frame (default 1.5).
--out                      folder for demo.gif, demo.mp4 and demo-poster.png (default: this folder).

It needs ffmpeg on the PATH (or --ffmpeg). The GIF uses a palette made from the clip itself, so the
text stays sharp; aim for under 5 MB, which GitHub shows without a wait.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def seconds(t):
    """'1:05.5' or '65.5' -> 65.5"""
    parts = [float(p) for p in t.strip().split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def parse_keep(spec):
    m = re.fullmatch(r"\s*([\d:.]+)\s*-\s*([\d:.]+)\s*(?:@\s*([\d.]+))?\s*", spec)
    if not m:
        sys.exit(f"--keep {spec!r}: use START-END or START-END@SPEED, like 0:41-0:55@2")
    a, b, speed = seconds(m.group(1)), seconds(m.group(2)), float(m.group(3) or 1)
    if b <= a or speed <= 0:
        sys.exit(f"--keep {spec!r}: END has to be after START, and SPEED above 0")
    return a, b, speed


def build_filter(keeps, crop, hold):
    """One filter graph: trim each piece, change its speed, join them, crop, hold the last frame."""
    chains, labels = [], []
    for i, (a, b, speed) in enumerate(keeps):
        chains.append(f"[0:v]trim=start={a}:end={b},setpts=(PTS-STARTPTS)/{speed}[p{i}]")
        labels.append(f"[p{i}]")
    if len(keeps) > 1:
        chains.append(f"{''.join(labels)}concat=n={len(keeps)}:v=1:a=0[cat]")
        src = "[cat]"
    else:
        src = labels[0] if keeps else "[0:v]"
    post = []
    if crop:
        x, y, w, h = crop
        post.append(f"crop={w}:{h}:{x}:{y}")
    if hold > 0:
        post.append(f"tpad=stop_mode=clone:stop_duration={hold}")
    chains.append(f"{src}{','.join(post) if post else 'null'}[clip]")
    return ";".join(chains)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg failed:\n" + r.stderr[-2000:])


def main():
    ap = argparse.ArgumentParser(description="Screen recording to README GIF and MP4.")
    ap.add_argument("video")
    ap.add_argument("--keep", action="append", default=[], metavar="START-END[@SPEED]")
    ap.add_argument("--crop", help="X,Y,W,H in pixels of the recording")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--hold", type=float, default=1.5)
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    a = ap.parse_args()

    if not a.ffmpeg:
        sys.exit("ffmpeg not found: install it, or pass --ffmpeg <path to ffmpeg>")
    if not os.path.isfile(a.video):
        sys.exit(f"Not found: {a.video}")
    keeps = [parse_keep(k) for k in a.keep]
    crop = None
    if a.crop:
        try:
            crop = [int(v) for v in a.crop.split(",")]
            assert len(crop) == 4
        except (ValueError, AssertionError):
            sys.exit("--crop takes X,Y,W,H, like 0,80,1600,900")
    os.makedirs(a.out, exist_ok=True)
    gif, mp4, poster = (os.path.join(a.out, n) for n in ("demo.gif", "demo.mp4", "demo-poster.png"))
    graph = build_filter(keeps, crop, a.hold)

    # 1. MP4: H.264, no sound, small, plays everywhere (X, Reddit, a GitHub comment)
    mp4_w = min(1280, crop[2] if crop else 1280)
    run([a.ffmpeg, "-y", "-i", a.video, "-filter_complex", f"{graph};[clip]scale={mp4_w}:-2:flags=lanczos,fps=30[v]",
         "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "28", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", mp4])
    # 2. GIF: a palette from the clip itself, then the frames dithered against it
    run([a.ffmpeg, "-y", "-i", mp4, "-filter_complex",
         f"fps={a.fps},scale={a.width}:-1:flags=lanczos,split[x][y];"
         "[x]palettegen=max_colors=128:stats_mode=diff[p];"
         "[y][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", gif])
    # 3. The first frame, for a link preview
    run([a.ffmpeg, "-y", "-i", mp4, "-frames:v", "1", "-vf", f"scale={a.width}:-1:flags=lanczos", poster])

    for path in (gif, mp4, poster):
        print(f"{os.path.getsize(path) / 1e6:6.2f} MB  {path}")
    if os.path.getsize(gif) > 5e6:
        print("The GIF is over 5 MB: try --fps 10, --width 880, or cut more with --keep.", file=sys.stderr)


if __name__ == "__main__":
    main()
