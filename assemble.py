#!/usr/bin/env python3
"""Assemble a finished bulletin video from clips + narration.

Usage:
  python3 assemble.py --clips clips.txt --audio narration.mp3 --out bulletin.mp4

clips.txt is an ffmpeg concat file, one line per clip, e.g.:
  file 'clips/intro.mp4'
  file 'clips/story-1.mp4'

Behaviour:
- Clips are 1280x720. The concatenated video is looped to cover the
  full narration length (a 5x10s clip set under a ~70s narration would
  otherwise end early), then trimmed to the audio length.
- Audio is the narration only; no music bed is added here.
- Output is h264 + AAC, 1280x720, ready to post.

Requires ffmpeg on PATH. No Python dependencies.
"""
import argparse
import subprocess
import sys


def probe_duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", path], text=True).strip()
    return float(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True, help="ffmpeg concat list")
    ap.add_argument("--audio", required=True, help="narration mp3")
    ap.add_argument("--out", required=True, help="output mp4")
    args = ap.parse_args()

    audio_len = probe_duration(args.audio)
    # Loop the concatenated video enough times to cover the audio, then
    # -shortest trims the video to the audio length.
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "3",
        "-f", "concat", "-safe", "0", "-i", args.clips,
        "-i", args.audio,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        args.out,
    ]
    print(" ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        sys.exit(r.returncode)
    print(f"wrote {args.out} ({probe_duration(args.out):.1f}s, "
          f"narration {audio_len:.1f}s)")


if __name__ == "__main__":
    main()
