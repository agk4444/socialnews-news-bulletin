#!/usr/bin/env python3
"""Build a vertical 1080x1920 Reel from a bulletin segments manifest.

This is a TEST / separate cut, not a replacement for the landscape
bulletin: the landscape version (assemble.py) is the full bulletin;
this script re-cuts the same narration into a 9:16 Reel for
Instagram, where landscape video would be letterboxed or cropped.

Layout per segment (1080x1920):
  - Background: the story photo, scaled to fill the frame, heavily
    blurred and slightly darkened. A blurred background is a
    background, not the photo itself, so cropping it to fill is
    fine — the sharp photo below is never cropped.
  - Foreground: the story photo itself, fitted (never cropped) into
    a 1000px-wide box, rounded corners + feather + soft shadow
    (same blended-inset treatment as add_insets.py), centred in the
    upper/middle area. Portrait photos keep their own narrower
    shape; the blurred background shows beside them.
  - Motion: both background and foreground slowly zoom in over
    the segment (Ken Burns via zoompan). A still photo with no
    motion reads as a slideshow, not a video — the first Reel test
    was criticised for exactly that, so motion is not optional here.
  - Headline: a lower-third text bar below the photo (never in the
    bottom ~250px, which Instagram's UI covers), white bold text on
    a semi-transparent black box, wrapped to fit.
  - Logo: the transparent SocialNews logo, top-right, 160px —
    same placement as the landscape bulletin.
  - Segments with no photo (intro/closing) use their generic clip
    as the blurred background and the logo, large and centred,
    as the foreground instead.

Usage:
  python3 assemble_reel.py --segments run/segments.json \\
      --segment-images 1:photo1.jpg 2:photo2.jpg \\
      --titles run/titles.json --logo logo-transparent.png \\
      --out reel-<YYYYMMDD>.mp4
  titles.json is {"1": "Headline for segment 1", ...}; segments
  without a title get no lower third. Segment start/end and
  durations come from segments.json (duration_s, or the audio
  file if duration_s is absent).

Requires ffmpeg/ffprobe on PATH and Pillow. Output is h264 + AAC,
1080x1920. Audio is the segment narration, copied per segment —
the Reel runs exactly as long as the narration (the Nov 2 test
runs 96.3s; a posting cut should be tightened under 90s, since
some Instagram accounts still cap Reels at 90s even though the
general limit is now 3 minutes).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from add_insets import build_blended_inset, probe_duration  # noqa: E402

W, H = 1080, 1920
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        sys.exit(r.returncode)
    return r


def probe_size(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0", path], text=True).strip()
    w, h = out.split(",")
    return int(w), int(h)


def escape_drawtext(text):
    # drawtext escapes: backslash, colon, single quote, percent.
    return (text.replace("\\", "\\\\").replace(":", "\\:")
                .replace("'", "\\'").replace("%", "\\%"))


def wrap_title(title, width=30):
    return "\n".join(textwrap.wrap(title, width=width))


def build_segment_clip_inset(seg, image, title, logo, tmp, idx):
    """Landscape formula, vertical: moving clip + photo inset.

    This is the layout that actually works in the landscape
    bulletin, adapted to 9:16 instead of inventing a still-photo
    layout (which is why Reel v1/v2 looked static):
      - Background: the segment's generic clip, centre-cropped to
        fill 1080x1920. Cropping a generic clip is fine — it is not
        a story photo, and the no-crop rule is for photos, which
        are handled below, never cropped.
      - Foreground: the story photo as a blended inset (same
        treatment as add_insets.py: fitted, never cropped, rounded
        + feather + shadow), centred, with a fade in/out over the
        segment — implemented here with looped-image fade, the
        same trap as add_insets.py: a single-image fade never
        advances, so the inset input must be looped.
      - Headline: at the top, below the logo, so Instagram's
        bottom UI never covers it.
    Segments with no photo (intro/closing) use the clip
    full-screen with the logo large and centred.
    """
    dur = seg.get("duration_s") or probe_duration(seg["audio"])
    out = os.path.join(tmp, f"reel-clip-seg-{idx}.mp4")
    clip = seg["clip"]
    inputs = ["ffmpeg", "-y", "-stream_loop", "3", "-i", clip]
    filt = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},format=yuv420p[bg]")
    prev = "bg"
    next_in = 1
    if image:
        fg_png = os.path.join(tmp, f"clip-fg-{idx}.png")
        total_w, total_h = build_blended_inset(
            image, fg_png, 920, 560, 36, 16, 8, 10, 110)
        fg_x = (W - total_w) // 2
        fg_y = 1050
        # Looped inset input: see add_insets.py trap 1.
        inputs += ["-loop", "1", "-framerate", "25", "-i", fg_png]
        filt += (f";[{next_in}:v]format=yuva420p,"
                 f"fade=t=in:st=0:d=0.5:alpha=1,"
                 f"fade=t=out:st={max(0.0, dur - 0.5)}:d=0.5:alpha=1"
                 f"[fg];[bg][fg]overlay={fg_x}:{fg_y}[v0]")
        prev = "v0"
        next_in += 1
    if logo:
        inputs += ["-i", logo]
        if image:
            filt += (f";[{next_in}:v]scale=160:160:"
                     "force_original_aspect_ratio=decrease,"
                     f"format=rgba[lg];[{prev}][lg]overlay="
                     f"{W - 160 - 20}:20[v1]")
            prev = "v1"
        else:
            filt += (f";[{next_in}:v]scale=360:360:"
                     "force_original_aspect_ratio=decrease,"
                     f"format=rgba[lg];[{prev}][lg]overlay="
                     "(W-w)/2:650[v1]")
            prev = "v1"
        next_in += 1
    if title:
        tf = os.path.join(tmp, f"clip-title-{idx}.txt")
        with open(tf, "w", encoding="utf-8") as f:
            f.write(wrap_title(title))
        y = 220 if image else 1150
        filt += (f";[{prev}]drawtext=fontfile={FONT}:"
                 f"textfile='{tf}':fontsize=52:fontcolor=white:"
                 "box=1:boxcolor=0x000000AA:boxborderw=30:"
                 f"x=(w-text_w)/2:y={y}[vout]")
        prev = "vout"
    else:
        filt += f";[{prev}]null[vout]"
    inputs += ["-i", seg["audio"]]
    run(inputs + ["-filter_complex", filt,
                  "-map", "[vout]", "-map", f"{next_in}:a:0",
                  "-t", str(dur), "-c:v", "libx264",
                  "-pix_fmt", "yuv420p", "-c:a", "aac",
                  "-shortest", out])
    return out


def build_segment(seg, image, title, logo, tmp, idx, layout="photo"):
    if layout == "clip-inset":
        return build_segment_clip_inset(seg, image, title, logo,
                                        tmp, idx)
    dur = seg.get("duration_s") or probe_duration(seg["audio"])
    out = os.path.join(tmp, f"reel-seg-{idx}.mp4")
    if image:
        # Blurred background from the photo, sharp photo on top.
        bg_png = os.path.join(tmp, f"bg-{idx}.png")
        # A single-frame background: scale-to-fill + blur via ffmpeg
        # needs a video input, so render the blurred background as
        # a still first, then loop it for the segment.
        run(["ffmpeg", "-y", "-v", "error", "-i", image,
             "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                    f"crop={W}:{H},boxblur=lr=20:lp=2,"
                    "eq=brightness=-0.08:saturation=0.8",
             "-frames:v", "1", bg_png])
        fg_png = os.path.join(tmp, f"fg-{idx}.png")
        total_w, total_h = build_blended_inset(
            image, fg_png, 1000, 1150, 36, 16, 8, 10, 110)
        fg_x = (W - total_w) // 2
        # Centre the photo in the 180..1380 zone, headline below.
        fg_y = 180 + max(0, (1200 - total_h) // 2)
        # Ken Burns motion: a still photo segment otherwise looks
        # like a slideshow, not a video (the first Reel test's
        # exact complaint). Both background and foreground slowly
        # zoom in over the segment, so the frame is always moving
        # under the narration. zoompan takes ONE input frame and
        # emits `frames` output frames; `on` is the output frame
        # number, so zoom grows linearly with segment progress.
        # Do NOT -loop these inputs: with a looped input, zoompan
        # restarts on every frame and the zoom never advances.
        frames = max(1, int(round(dur * 25)))
        inputs = ["ffmpeg", "-y", "-i", bg_png, "-i", fg_png]
        filt = (
            f"[0:v]zoompan=z='1+0.12*on/{frames}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={W}x{H}:fps=25[bg];"
            f"[1:v]zoompan=z='1+0.08*on/{frames}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={total_w}x{total_h}:fps=25[fg];"
            f"[bg][fg]overlay={fg_x}:{fg_y}[v0]"
        )
        next_in = 2
        if logo:
            inputs += ["-i", logo]
            filt += (f";[{next_in}:v]scale=160:160:"
                     "force_original_aspect_ratio=decrease,"
                     "format=rgba[lg];[v0][lg]overlay="
                     f"{W - 160 - 20}:20[v1]")
            prev = "v1"
            next_in += 1
        else:
            prev = "v0"
        if title:
            txt = escape_drawtext(wrap_title(title))
            # drawtext text with newlines: pass via a text file so
            # quoting stays safe.
            tf = os.path.join(tmp, f"title-{idx}.txt")
            with open(tf, "w", encoding="utf-8") as f:
                f.write(wrap_title(title))
            filt += (f";[{prev}]drawtext=fontfile={FONT}:"
                     f"textfile='{tf}':fontsize=52:fontcolor=white:"
                     "box=1:boxcolor=0x000000AA:boxborderw=30:"
                     "x=(w-text_w)/2:y=1420[vout]")
            prev = "vout"
        else:
            filt += f";[{prev}]null[vout]"
        inputs += ["-i", seg["audio"]]
        run(inputs + ["-filter_complex", filt,
                      "-map", "[vout]", "-map", f"{next_in}:a:0",
                      "-t", str(dur), "-c:v", "libx264",
                      "-pix_fmt", "yuv420p", "-c:a", "aac",
                      "-shortest", out])
    else:
        # Intro/closing: blurred generic clip background, logo large
        # and centred, title (if any) as the lower third.
        clip = seg["clip"]
        inputs = ["ffmpeg", "-y",
                  "-stream_loop", "3", "-i", clip]
        filt = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},boxblur=lr=20:lp=2,"
                "eq=brightness=-0.08:saturation=0.8[bg]")
        next_in = 1
        if logo:
            inputs += ["-i", logo]
            filt += (f";[{next_in}:v]scale=360:360:"
                     "force_original_aspect_ratio=decrease,"
                     "format=rgba[lg];[bg][lg]overlay="
                     f"(W-w)/2:650[v1]")
            prev = "v1"
            next_in += 1
        else:
            prev = "bg"
        if title:
            tf = os.path.join(tmp, f"title-{idx}.txt")
            with open(tf, "w", encoding="utf-8") as f:
                f.write(wrap_title(title))
            filt += (f";[{prev}]drawtext=fontfile={FONT}:"
                     f"textfile='{tf}':fontsize=56:fontcolor=white:"
                     "box=1:boxcolor=0x000000AA:boxborderw=30:"
                     "x=(w-text_w)/2:y=1150[vout]")
            prev = "vout"
        else:
            filt += f";[{prev}]null[vout]"
        inputs += ["-i", seg["audio"]]
        run(inputs + ["-filter_complex", filt,
                      "-map", "[vout]", "-map", f"{next_in}:a:0",
                      "-t", str(dur), "-c:v", "libx264",
                      "-pix_fmt", "yuv420p", "-c:a", "aac",
                      "-shortest", out])
    return out


def parse_mapping(specs):
    out = {}
    for spec in specs or []:
        idx, path = spec.split(":", 1)
        out[int(idx)] = path
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", required=True)
    ap.add_argument("--segment-images", nargs="+", default=[])
    ap.add_argument("--titles", help="JSON {segment_index: headline}")
    ap.add_argument("--logo", help="transparent logo png")
    ap.add_argument("--layout", default="photo",
                    choices=["photo", "clip-inset"],
                    help="photo: still photo as main visual (v1/v2, "
                         "static-looking); clip-inset: moving clip "
                         "full-screen + photo inset (landscape "
                         "formula, vertical)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    segs = json.load(open(args.segments))
    images = parse_mapping(args.segment_images)
    titles = {}
    if args.titles:
        titles = {int(k): v for k, v in json.load(open(args.titles)).items()}

    with tempfile.TemporaryDirectory() as tmp:
        built = []
        for i, s in enumerate(segs):
            idx = s.get("index", i)
            built.append(build_segment(s, images.get(idx),
                                       titles.get(idx), args.logo,
                                       tmp, idx, layout=args.layout))
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as f:
            for p in built:
                f.write(f"file '{os.path.abspath(p)}'\n")
            lst = f.name
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
             "-c", "copy", args.out])
        os.unlink(lst)

    print(f"wrote {args.out} ({probe_duration(args.out):.1f}s)")


if __name__ == "__main__":
    main()
