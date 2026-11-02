# SocialNews News Bulletin — reusable video pipeline

A news-reader-style video bulletin built from SocialNews.XYZ's own top
stories. One run = fetch top stories → pick 4 → draft a short bulletin
script → narrate it → generate generic studio visuals → assemble one MP4.

This repo holds the **pipeline, not the finished videos**. Finished MP4s
and narration are per-run outputs (see `.gitignore`); the narration
script for a run is kept under `examples/` so a past bulletin can be
checked later.

## The pipeline

### 1. Fetch top stories

```sh
python3 fetch_top.py --per-page 10 --out run/stories.json
```

Public, read-only API, no auth:
`https://www.socialnews.xyz/wp-json/socialnews/v1/articles?section=110`

Top section is id `110` — never substitute Politics. Known quirk:
`/articles` occasionally stalls while `/health` and `/search` still
pass; `fetch_top.py` retries 3 times with a 6s backoff, and if it still
stalls, retry later or fall back to `/search`.

### 2. Pick 4 stories

From `run/stories.json`, pick 4 distinct, major stories. Drop
same-event duplicates (an initial report + an update of one event
counts once), and favour a mix over four versions of one theme.
Record the picked story ids + URLs in the run notes.

### 3. Draft the bulletin script

Write `run/script.txt`, ~200–260 words (about 90–100 seconds spoken), original summary wording:

- Open: "Hello, this is your SocialNews bulletin for <day, date>."
- One short segment per story, in the picked order, each with the
  key fact, place, and number/date where the story gives one.
- Close: "That's your major stories bulletin from SocialNews XYZ."
- Headlines/excerpts with attribution + link are fine; do **not**
  republish full article text verbatim.
- Cross-check any major claim that isn't in the SocialNews story
  itself before it goes in the script.
- No real identifiable anchor person: the bulletin uses a generic
  narrator voice and generic studio visuals, never a real person's
  face or voice.

### 4. Narrate it

One voice for the whole bulletin (the Nov 1–2 runs used
`avocado_v2:MAI_03` via the Muse TTS tool):

```sh
tts speak --text-stdin --output run/narration.mp3 < run/script.txt
```

Write numbers, times, and abbreviations as they should sound
("twenty-one seventeen", not "21-17").

### 5. Generate visuals

One generic 1280×720, ~10s clip per segment: intro + one per story
(5 clips for a 4-story bulletin). Prompts must be generic — a news
studio, a courthouse exterior, a sports arena — never a recognisable
real person, and never a re-creation of a specific real event's
footage. Save them under `run/clips/` and list them in order in
`run/clips.txt` (ffmpeg concat format):

```
file 'clips/intro.mp4'
file 'clips/story-1.mp4'
...
```

Paths in `clips.txt` are relative to the `clips.txt` file itself
(ffmpeg concat rule), not to the working directory — `run/clips.txt`
lists `clips/...`, not `run/clips/...`.

### 6. Assemble — synced, with logo

For a finished bulletin, use the **synced** mode, not the old looped
mode. Split the script into paragraphs, narrate each paragraph
separately (same voice), generate one clip per paragraph, then:

```sh
python3 segment_manifest.py --script run/script.txt \
    --audios run/seg-0.mp3 run/seg-1.mp3 run/seg-2.mp3 run/seg-3.mp3 run/seg-4.mp3 \
    --clips run/clips/clip-0.mp4 run/clips/clip-1.mp4 run/clips/clip-2.mp4 run/clips/clip-3.mp4 run/clips/clip-4.mp4 \
    --out run/segments.json

python3 assemble.py --segments run/segments.json \
    --logo logo.png --logo-size 160 --logo-position top-right \
    --out bulletin-<YYYYMMDD>.mp4
```

Why this keeps narration and video in sync: each segment's clip is
looped/trimmed to exactly that segment's narration duration, and
segments are concatenated in script order. So the Florida clip plays
while the Florida story is spoken, the Delhi clip while the Delhi
story is spoken, and a missing segment can't silently shift the rest
— `segment_manifest.py` fails on a count mismatch. This is
segment-level sync; word-level sync would need forced alignment
(e.g. Whisper timestamps) and is not worth it here — a viewer
notices a story playing under the wrong narration, not a word
landing a fraction of a second early.

Logo: `--logo` takes the square SocialNews.XYZ logo file, scales it
to fit a square (`--logo-size`, default 160px, aspect preserved with
transparent padding), and overlays it in a corner for the whole
video (`--logo-position`: top-right, top-left, bottom-right,
bottom-left). Prefer `logo-transparent.png` (white background
converted to alpha, feathered edges) over `logo.png` — a white
square reads as a sticker pasted on the video, while the transparent
version sits like a broadcast watermark, with the video showing
through between the letters. Both files are committed in this repo;
pass the path explicitly, the pipeline never guesses a logo URL.

Voices per story: narration is per segment, so voices can change
per segment. The default voice is used for general/US stories; for
Indian stories, narrate those segments with an Indian-accent voice
from the TTS catalog — the Nov 2 run used
`avocado_v2:vd3_vd2_r8_rep1k_0369_v068_28k_g5k` (male, Indian, calm,
moderate pacing) for the ED-raid and Modi-summit segments, which
pronounces names like Hoshiarpur, Arora, and Modi in Indian English
rather than American English. Always check the TTS return value:
if it reports a different voice id than requested, a substitution
happened and the segment must be re-rendered, not shipped.

### 7. Story-photo insets (optional, blended)

After assembling, overlay each story's featured photo as a blended
inset — bottom-right by default, so it never clashes with the
top-right logo:

```sh
python3 add_insets.py --video bulletin-<YYYYMMDD>.mp4 \
    --out bulletin-<YYYYMMDD>-inset.mp4 \
    --segments run/segments.json \
    --segment-images 1:run/insets/florida.jpg 2:run/insets/trump.jpg
```

Segment numbers are the manifest indices (intro is 0, so story
segments are 1–4 in a 4-story bulletin); segments with no image get
no inset. Or pass an explicit list instead:
`--insets run/insets.json` with `{"start", "end", "image"}` entries.

The inset is not a pasted box: the full photo is fitted inside a
440×248 maximum (never cropped — a portrait photo keeps its own
narrower shape, so the video shows through beside it), with rounded
corners, feathered edges, a soft drop shadow, and a 0.5s fade in/out
at its segment boundaries. Requires Pillow (`pip install Pillow`) in
addition to ffmpeg. The same photo-rights caution as step 5 applies:
a story photo used as an inset is still a reuse in a new medium, so
check the wire licence before posting the video publicly.

The legacy looped mode still exists for quick drafts:

```sh
python3 assemble.py --clips run/clips.txt --audio run/narration.mp3 --out bulletin-<YYYYMMDD>.mp4
```

Output in both modes is h264 + AAC, 1280×720. Verify before
delivery: duration matches the narration, audio is intelligible
throughout, each clip matches the story being spoken, and the logo
is legible in the corner without covering captions or faces.

### 8. Vertical Reel cut (optional)

For Instagram, re-cut the same segments to 1080×1920 with
`assemble_reel.py`. Use the **clip-inset** layout — it is the
landscape formula, vertical, and it is the approved look (Nov 2
test, v3). The earlier photo layout (still photo as the main
visual, even with a Ken Burns zoom) looked like a slideshow, not a
video, because its zoom was only 8–12% over a whole segment.

```sh
python3 assemble_reel.py --layout clip-inset \
    --segments run/segments-indian.json \
    --segment-images 1:run/insets/florida.jpg 2:run/insets/trump.jpg \
        3:run/insets/ed.jpg 4:run/insets/modi.jpg \
    --titles run/titles-nov2.json --logo logo-transparent.png \
    --out bulletin-<YYYYMMDD>-reel.mp4
```

- Background: each segment's generic clip, centre-cropped to fill
  1080×1920. Cropping a generic clip is fine — the no-crop rule is
  for story photos, which are never cropped here either.
- Foreground: the story photo as a blended inset (fitted, rounded,
  feathered, shadowed, 0.5s fade in/out), centred in the lower
  middle. The inset input must be looped — a single-image fade
  never advances (same trap as step 7).
- Headline: at the top, below the logo, so Instagram's bottom UI
  never covers it. Intro/closing use the clip full-screen with the
  logo large and centred.
- Titles: a JSON file mapping segment index to headline
  (`{"0": "...", "1": "..."}`), one per segment.
- Posting cut: keep it under 90 seconds — some Instagram accounts
  still cap Reels at 90s even though standard Reels allow up to
  3 minutes. The Nov 2 test ran 96.3s, so a posting version needs a
  tighter script/narration, not just a re-cut.
- Same photo-rights caution as step 5 applies before posting
  publicly: wire/agency story photos need a licence check for
  Instagram video reuse.

## Examples

- `examples/2026-11-01-script.txt` — the first bulletin (Nov 1, 2026):
  US midterms rallies, Mahadev/CBI, Hylo Open double, hockey 4–2.
  Finished video was ~69s, 1280×720.
- `examples/2026-11-02-script.txt` — the second bulletin (Nov 2, 2026),
  the first run through this repo's pipeline: Florida Learjet crash,
  Trump midterm push, ED raid in Punjab, Modi renewable-energy summit.

## What this is not

- Not a scheduled job: a run is started by a person (or by an agent
  on request), not by a cron, until someone explicitly asks for a
  schedule.
- Not a live feed: stories are a snapshot at fetch time, and the
  script is written from that snapshot.
- Not an anchor: there is no presenter, real or synthetic, in these
  videos — narration + generic visuals only.
