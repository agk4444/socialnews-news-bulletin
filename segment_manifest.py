#!/usr/bin/env python3
"""Build segments.json for synced assembly.

Workflow for a synced bulletin:
  1. Split run/script.txt into paragraphs (intro + one per story).
  2. Narrate EACH paragraph separately (one TTS call per paragraph):
       seg-0.mp3, seg-1.mp3, ...  (same voice throughout)
  3. Generate one generic clip per paragraph: clip-0.mp4, clip-1.mp4, ...
  4. Run this script to pair them in order and record durations:
       python3 segment_manifest.py --script run/script.txt \\
           --audios run/seg-0.mp3 run/seg-1.mp3 ... \\
           --clips run/clips/clip-0.mp4 run/clips/clip-1.mp4 ... \\
           --out run/segments.json
     It fails if the counts don't match, so a missing segment can't
     silently shift every later story out of sync.
  5. Assemble:
       python3 assemble.py --segments run/segments.json \\
           --logo logo.png --out bulletin.mp4

No Python dependencies (ffprobe only, for durations).
"""
import argparse
import json
import subprocess
import sys


def duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", path], text=True).strip()
    return float(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--audios", nargs="+", required=True)
    ap.add_argument("--clips", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    paras = [p.strip() for p in open(args.script).read().split("\n\n") if p.strip()]
    if not (len(paras) == len(args.audios) == len(args.clips)):
        print(f"count mismatch: script paragraphs={len(paras)}, "
              f"audios={len(args.audios)}, clips={len(args.clips)}",
              file=sys.stderr)
        sys.exit(2)
    segs = []
    for i, (a, c) in enumerate(zip(args.audios, args.clips)):
        segs.append({"index": i, "clip": c, "audio": a,
                     "duration_s": round(duration(a), 2),
                     "text": paras[i][:120]})
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(segs, f, indent=2, ensure_ascii=False)
    total = sum(s["duration_s"] for s in segs)
    print(f"wrote {args.out}: {len(segs)} segments, {total:.1f}s total")
    for s in segs:
        print(f"  seg {s['index']}: {s['duration_s']}s  {s['text']}")


if __name__ == "__main__":
    main()
