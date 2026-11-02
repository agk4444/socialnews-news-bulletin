#!/usr/bin/env python3
"""Assemble a finished bulletin video from clips + narration.

Two modes:

1. Simple (legacy, NOT synced):
  python3 assemble.py --clips clips.txt --audio narration.mp3 --out bulletin.mp4
  Clips are concatenated, looped to cover the narration, then trimmed.
  Visuals do NOT line up with story segments — fine for a quick draft.

2. Synced (recommended) — one clip + one narration file per segment:
  python3 assemble.py --segments segments.json --out bulletin.mp4
  segments.json (see segment_manifest.py) is a list of:
    {"clip": "run/clips/intro.mp4", "audio": "run/seg-0.mp3"}
  Each segment's clip is looped/trimmed to exactly that segment's
  narration duration, segments are concatenated in order, so the
  Florida clip plays while the Florida story is spoken, and so on.
  This is segment-level sync. Word-level sync would need forced
  alignment (e.g. Whisper timestamps) and is not done here — segment
  sync is what a viewer actually notices.

Logo overlay (either mode):
  --logo logo.png [--logo-size 160] [--logo-position top-right]
  The logo is scaled to fit a square of --logo-size pixels (aspect
  preserved, transparent padding), then overlaid in a corner for the
  whole video: top-right (default), top-left, bottom-right, bottom-left.
  Use the square SocialNews.XYZ logo file here — if the source is a
  wide banner, it will still work, but it will sit in a square box
  with side padding, so prefer the square version.

Requires ffmpeg/ffprobe on PATH. No Python dependencies.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

POSITIONS = {
    "top-right": "W-w-20:20",
    "top-left": "20:20",
    "bottom-right": "W-w-20:H-h-20",
    "bottom-left": "20:H-h-20",
}


def run(cmd, err_tail=2000):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-err_tail:], file=sys.stderr)
        sys.exit(r.returncode)
    return r


def probe_duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", path], text=True).strip()
    return float(out)


def build_segment(clip, audio, out):
    """One segment: clip looped/trimmed to exactly the audio length."""
    dur = probe_duration(audio)
    run([
        "ffmpeg", "-y",
        "-stream_loop", "3", "-i", clip,
        "-i", audio,
        "-map", "0:v:0", "-map", "1:a:0",
        "-t", str(dur),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        out,
    ])
    return out


def concat_segments(segment_files, out):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in segment_files:
            f.write(f"file '{os.path.abspath(p)}'\n")
        lst = f.name
    run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", lst,
        "-c", "copy", out,
    ])
    os.unlink(lst)


def apply_logo(video_in, logo, size, position, out):
    xy = POSITIONS[position]
    filt = (
        f"[1:v]scale={size}:{size}:force_original_aspect_ratio=decrease,"
        f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
        f"format=rgba[logo];[0:v][logo]overlay={xy}:format=yuv420[vout]"
    )
    run([
        "ffmpeg", "-y", "-i", video_in, "-i", logo,
        "-filter_complex", filt,
        # Map the FILTERED output, not 0:v:0 — mapping 0:v:0 bypasses
        # the overlay entirely (caught by a pixel check in testing).
        "-map", "[vout]", "-map", "0:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy", out,
    ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", help="ffmpeg concat list (simple mode)")
    ap.add_argument("--audio", help="narration mp3 (simple mode)")
    ap.add_argument("--segments", help="segments.json (synced mode)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--logo", help="square logo image (png/jpg)")
    ap.add_argument("--logo-size", type=int, default=160)
    ap.add_argument("--logo-position", choices=list(POSITIONS),
                    default="top-right")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        if args.segments:
            segs = json.load(open(args.segments))
            if len(segs) < 1:
                print("segments.json is empty", file=sys.stderr)
                sys.exit(2)
            built = []
            for i, s in enumerate(segs):
                built.append(build_segment(
                    s["clip"], s["audio"],
                    os.path.join(tmp, f"seg-{i}.mp4")))
            video = os.path.join(tmp, "synced.mp4")
            concat_segments(built, video)
        elif args.clips and args.audio:
            audio_len = probe_duration(args.audio)
            video = os.path.join(tmp, "simple.mp4")
            run([
                "ffmpeg", "-y",
                "-stream_loop", "3",
                "-f", "concat", "-safe", "0", "-i", args.clips,
                "-i", args.audio,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest",
                video,
            ])
        else:
            print("need --segments, or --clips + --audio", file=sys.stderr)
            sys.exit(2)

        if args.logo:
            apply_logo(video, args.logo, args.logo_size,
                       args.logo_position, args.out)
        else:
            run(["cp", video, args.out])

    print(f"wrote {args.out} ({probe_duration(args.out):.1f}s)")


if __name__ == "__main__":
    main()
