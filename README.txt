========================================
Duplicate File Finder (dup_find.py)
========================================
Coded by: Muse Spark (Meta AI assistant)
Curated by: smallrug2
License: MIT (see LICENSE file)

WHAT IT DOES:
Walks a directory tree, groups files by size first (fast path), then
SHA-256 hashes only size-collision candidates (chunked reads, progress
on stderr). Reports each duplicate group (files + wasted bytes) and
total reclaimable bytes. --delete is permanent (no trash) and requires --yes.

REQUIREMENTS:
Python 3.8+ only - no extra packages needed (stdlib only).

HOW TO RUN:
python dup_find.py --help
python dup_find.py --dir C:\Photos
python dup_find.py --dir ./docs --min-kb 100
python dup_find.py --dir ./media --delete --yes

PLATFORM:
Windows + Linux + Mac: yes.

CREDITS:
- Coded by Muse Spark (Meta AI assistant) for smallrug2's open-source collection.
- If this script helped you, a star on the repo is appreciated.
