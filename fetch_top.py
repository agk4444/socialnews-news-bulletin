#!/usr/bin/env python3
"""Fetch the latest Top stories from SocialNews.XYZ.

Public, read-only API, no auth:
  https://www.socialnews.xyz/wp-json/socialnews/v1

Usage:
  python3 fetch_top.py [--per-page 10] [--out stories.json]

Output is a JSON file with one entry per story: id, title, url,
published_at, section, attribution (wire), image url, and the first
~600 characters of content_text (an excerpt, never the full article).

Notes from real runs:
- The correct Top section is id 110. Never substitute Politics.
- /articles occasionally stalls while /health and /search still pass.
  This script retries (3 attempts, 6s backoff) before giving up;
  if it still stalls, retry later or use /search as a fallback.
- Headlines/excerpts with attribution + link are fine to reuse;
  do NOT republish full article text verbatim.
- Duplicate coverage of one event (e.g. an initial report and an
  update) can appear as two items. Dedupe by exact normalised title
  here; the story-picking step must still drop same-event dupes.
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.socialnews.xyz/wp-json/socialnews/v1"
TOP_SECTION = "110"


def get(path, params=None, timeout=25):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(
        url, headers={"User-Agent": "socialnews-news-bulletin/1.0"})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(6)
    raise RuntimeError(f"failed to fetch {url}: {last_err}")


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-page", type=int, default=10)
    ap.add_argument("--out", default="stories.json")
    args = ap.parse_args()

    data = get("/articles", {"section": TOP_SECTION, "per_page": args.per_page})
    seen, stories = set(), []
    for it in data.get("items", []):
        key = norm_title(it.get("title"))
        if not key or key in seen:
            continue
        seen.add(key)
        stories.append({
            "id": it.get("id"),
            "title": it.get("title"),
            "url": it.get("url"),
            "published_at": it.get("published_at"),
            "section": (it.get("section") or {}).get("slug"),
            "attribution": (it.get("attribution") or {}).get("wire"),
            "image": (it.get("image") or {}).get("url"),
            "excerpt": (it.get("content_text") or "")[:600],
        })
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "stories": stories}, f, indent=2, ensure_ascii=False)
    print(f"wrote {len(stories)} stories to {args.out}")
    for s in stories:
        print(f"  {s['id']}  {s['title']}")


if __name__ == "__main__":
    main()
