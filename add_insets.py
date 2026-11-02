#!/usr/bin/env python3
"""Overlay story photos as blended insets on a finished bulletin video.

The inset is NOT a pasted box: each story photo is fitted (full photo,
never cropped) into a box, given rounded corners with feathered edges,
a soft drop shadow, and a short fade in/out, so it blends into the
video behind it instead of sitting on top like a sticker.

Usage — explicit inset list:
  python3 add_insets.py --video bulletin.mp4 --out bulletin-inset.mp4 \\
      --insets run/insets.json
  where insets.json is a list of:
    {"start": 7.2, "end": 36.0, "image": "run/insets/florida.jpg"}

Usage — from a segments manifest (the usual pipeline path):
  python3 add_insets.py --video bulletin.mp4 --out bulletin-inset.mp4 \\
      --segments run/segments.json \\
      --segment-images 1:run/insets/florida.jpg 2:run/insets/trump.jpg
  Segment start/end times are computed cumulatively from each
  segment's duration_s. Segments with no image get no inset (intro
  and closing normally have none).

Defaults match the Nov 2, 2026 bulletin that this was built from:
bottom-right, 440x248 photo box, 0.5s fade, 20px margin from the edge
(the logo sits top-right, so bottom-right never clashes with it).

Two traps, both caught in testing and encoded here so they stay fixed:

1. Fade needs a LOOPED image input. A single-image input is one frame
   whose timestamp never advances, so a fade filter on it never
   progresses — the first attempt rendered completely invisible
   insets with no error. Every inset input here is `-loop 1`, so its
   timestamps advance with the main video and the fade in/out
   actually happen at the segment boundaries.

2. Map the FILTERED output, not 0:v:0 — mapping the raw input
   bypasses the overlay entirely (same trap as the logo overlay
   in assemble.py, caught there by a pixel check).

Requires ffmpeg/ffprobe on PATH and Pillow (pip install Pillow) for
the blended inset images. The finished video is h264 + AAC, audio
copied untouched.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    print("add_insets.py needs Pillow: pip install Pillow", file=sys.stderr)
    sys.exit(2)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        sys.exit(r.returncode)
    return r


def probe_duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", path], text=True).strip()
    return float(out)


def probe_size(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0", path], text=True).strip()
    w, h = out.split(",")
    return int(w), int(h)


def build_blended_inset(image_path, out_path, box_w, box_h, radius,
                        feather, shadow_off, shadow_blur, shadow_alpha):
    """Fit the full photo into box_w x box_h, rounded + feathered.

    The photo is never cropped: it is scaled down to fit inside the
    box, and the inset takes the photo's own fitted size — not the
    box size. That matters: applying a full-box alpha mask to a
    portrait photo would turn its side padding into opaque black
    bars (caught by a pixel check in testing). With the mask sized
    to the photo itself, the video behind shows through beside a
    portrait photo instead. The rounded-corner mask is blurred by
    `feather` pixels, so the photo's edges dissolve into the video
    behind instead of ending in a hard line. A soft shadow, offset
    down-right, sits behind the photo so it still lifts off busy
    backgrounds. Total canvas is the fitted photo plus the shadow
    offset and blur room, so callers must position by the canvas
    size, not the box size.
    """
    # Open by content, not extension: a story image saved as .jpg
    # may actually be a PNG (seen in the Nov 2 run).
    src = Image.open(image_path).convert("RGB")
    src.thumbnail((box_w, box_h), Image.LANCZOS)
    fw, fh = src.width, src.height
    box = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    box.paste(src, (0, 0))
    mask = Image.new("L", (fw, fh), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, fw - 1, fh - 1], radius=radius,
                        fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather))
    box.putalpha(mask)

    # Room for the shadow blur past the shadow rect on the
    # bottom/right; the photo itself covers the top/left spread.
    total_w = fw + shadow_off + shadow_blur
    total_h = fh + shadow_off + shadow_blur
    canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([shadow_off, shadow_off,
                          shadow_off + fw - 1,
                          shadow_off + fh - 1], radius=radius,
                         fill=(0, 0, 0, shadow_alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(box, (0, 0))
    canvas.save(out_path)
    return total_w, total_h


def position(total_w, total_h, video_w, video_h, corner, margin):
    if corner == "bottom-right":
        return f"{video_w - total_w - margin}:{video_h - total_h - margin}"
    if corner == "bottom-left":
        return f"{margin}:{video_h - total_h - margin}"
    if corner == "top-right":
        return f"{video_w - total_w - margin}:{margin}"
    return f"{margin}:{margin}"  # top-left


def parse_segment_images(specs):
    """Parse '1:path.jpg' specs into {segment_index: path}."""
    out = {}
    for spec in specs:
        try:
            idx, path = spec.split(":", 1)
            out[int(idx)] = path
        except ValueError:
            print(f"bad --segment-images spec (want N:path): {spec}",
                  file=sys.stderr)
            sys.exit(2)
    return out


def insets_from_segments(segments_path, mapping):
    segs = json.load(open(segments_path))
    insets = []
    t = 0.0
    for i, s in enumerate(segs):
        dur = s.get("duration_s")
        if dur is None:
            dur = probe_duration(s["audio"])
        idx = s.get("index", i)
        if idx in mapping:
            insets.append({"start": round(t, 2), "end": round(t + dur, 2),
                           "image": mapping[idx]})
        t += dur
    return insets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="finished bulletin mp4")
    ap.add_argument("--out", required=True)
    ap.add_argument("--insets", help="JSON list of start/end/image")
    ap.add_argument("--segments", help="segments.json (with --segment-images)")
    ap.add_argument("--segment-images", nargs="+", default=[],
                    help="N:path, one per segment that gets an inset")
    ap.add_argument("--box-width", type=int, default=440)
    ap.add_argument("--box-height", type=int, default=248)
    ap.add_argument("--radius", type=int, default=28)
    ap.add_argument("--feather", type=int, default=14)
    ap.add_argument("--shadow-offset", type=int, default=8)
    ap.add_argument("--shadow-blur", type=int, default=10)
    ap.add_argument("--shadow-alpha", type=int, default=110)
    ap.add_argument("--fade", type=float, default=0.5)
    ap.add_argument("--position", default="bottom-right",
                    choices=["bottom-right", "bottom-left",
                             "top-right", "top-left"])
    ap.add_argument("--margin", type=int, default=20)
    args = ap.parse_args()

    if args.insets:
        insets = json.load(open(args.insets))
    elif args.segments and args.segment_images:
        insets = insets_from_segments(
            args.segments, parse_segment_images(args.segment_images))
    else:
        print("need --insets, or --segments + --segment-images",
              file=sys.stderr)
        sys.exit(2)
    if not insets:
        print("no insets to apply", file=sys.stderr)
        sys.exit(2)
    for ins in insets:
        if not os.path.exists(ins["image"]):
            print(f"inset image not found: {ins['image']}", file=sys.stderr)
            sys.exit(2)
        if not ins["end"] > ins["start"] > 0:
            print(f"bad inset times: {ins}", file=sys.stderr)
            sys.exit(2)

    video_w, video_h = probe_size(args.video)
    with tempfile.TemporaryDirectory() as tmp:
        inputs = ["ffmpeg", "-y", "-i", args.video]
        filters = []
        prev = "0:v"
        for i, ins in enumerate(insets):
            png = os.path.join(tmp, f"inset-{i}.png")
            total_w, total_h = build_blended_inset(
                ins["image"], png, args.box_width, args.box_height,
                args.radius, args.feather, args.shadow_offset,
                args.shadow_blur, args.shadow_alpha)
            xy = position(total_w, total_h, video_w, video_h,
                          args.position, args.margin)
            # -loop 1 is load-bearing: see module docstring trap 1.
            inputs += ["-loop", "1", "-framerate", "25", "-i", png]
            fade_in = ins["start"]
            fade_out = ins["end"] - args.fade
            filters.append(
                f"[{i + 1}:v]format=yuva420p,"
                f"fade=t=in:st={fade_in}:d={args.fade}:alpha=1,"
                f"fade=t=out:st={fade_out}:d={args.fade}:alpha=1"
                f"[in{i}]")
            nxt = f"v{i}" if i < len(insets) - 1 else "vout"
            filters.append(
                f"[{prev}][in{i}]overlay={xy}:"
                f"enable='between(t,{ins['start']},{ins['end']})'"
                f"[{nxt}]")
            prev = nxt
        cmd = inputs + ["-filter_complex", ";".join(filters),
                        "-map", "[vout]", "-map", "0:a:0",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "copy",
                        "-t", str(probe_duration(args.video)), args.out]
        run(cmd)

    print(f"wrote {args.out} ({probe_duration(args.out):.1f}s, "
          f"{len(insets)} insets)")


if __name__ == "__main__":
    main()
