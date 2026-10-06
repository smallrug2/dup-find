"""Duplicate file finder (size-first, then SHA-256).

Walks a directory tree, groups files by size (fast path), then hashes
only size-collision candidates with chunked SHA-256 reads. Reports each
duplicate group (files + wasted bytes) plus total reclaimable bytes.

Usage examples:
    python dup_find.py --dir C:\\Photos
    python dup_find.py --dir ./docs --min-kb 100
    python dup_find.py --dir ./media --delete --yes

Platform notes:
    Windows + Linux + macOS. All paths handled with pathlib; no
    symlink loops followed by default. Unreadable files are skipped
    with a warning count, never a crash. Deletion is permanent and
    does NOT use the trash/recycle bin.

Dependencies:
    Standard library only (argparse, hashlib, os, sys, pathlib).
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

CHUNK = 1024 * 1024  # read 1 MiB at a time


def sha256_of(path, errors):
    """Return hex SHA-256 of file, or None if unreadable (counts warning)."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError) as e:
        errors.append("skip unreadable %s: %s" % (path, e))
        return None


def iter_files(root):
    """Yield file Paths under root without following dir symlinks."""
    # os.walk with followlinks=False is cross-platform and avoids loops.
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            p = Path(dirpath) / name
            # Skip symlinked files themselves? Include target stat via
            # is_file (follows file symlinks) but guard broken links.
            try:
                if p.is_file():
                    yield p
            except OSError:
                continue  # unreadable entry: caller counts via stat stage


def build_parser():
    p = argparse.ArgumentParser(
        description="Find duplicate files by size then SHA-256. "
                    "WARNING: --delete permanently deletes files (no trash)."
    )
    p.add_argument("--dir", required=True, help="Root directory to scan.")
    p.add_argument("--min-kb", type=float, default=1,
                   help="Ignore files smaller than this (KB, default: %(default)s).")
    p.add_argument("--delete", action="store_true",
                   help="PERMANENTLY delete duplicates (keep first file per "
                        "group). Requires --yes. Nothing goes to trash.")
    p.add_argument("--yes", action="store_true",
                   help="Confirm --delete. Without this, --delete refuses.")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    root = Path(args.dir).expanduser()
    if not root.exists():
        print("error: directory not found: %s" % args.dir, file=sys.stderr)
        return 1
    if not root.is_dir():
        print("error: not a directory: %s" % args.dir, file=sys.stderr)
        return 1
    if args.min_kb < 0:
        print("error: --min-kb must be >= 0", file=sys.stderr)
        return 2

    # Safety gate: --delete needs explicit --yes.
    if args.delete and not args.yes:
        print("error: --delete requires --yes (deletion is permanent, no trash). "
              "Re-run with --delete --yes to confirm.", file=sys.stderr)
        return 2

    min_bytes = int(args.min_kb * 1024)

    # Stage 1: group by size (fast, no hashing yet).
    by_size = {}
    skipped = 0
    total_files = 0
    try:
        entries = list(iter_files(root))
    except OSError as e:
        print("error: cannot walk %s: %s" % (root, e), file=sys.stderr)
        return 1

    for p in entries:
        total_files += 1
        try:
            size = p.stat().st_size
        except (OSError, PermissionError):
            skipped += 1
            continue
        if size < min_bytes:
            continue
        by_size.setdefault(size, []).append(p)

    candidates = [lst for lst in by_size.values() if len(lst) > 1]
    to_hash = sum(len(lst) for lst in candidates)

    if not candidates:
        print("scanned %d file(s); no size collisions -> no duplicates." % total_files)
        if skipped:
            print("warning: skipped %d unreadable file(s)." % skipped, file=sys.stderr)
        print("total reclaimable: 0 bytes.")
        return 0

    # Stage 2: hash only candidates, with progress on stderr.
    errors = []
    by_hash = {}  # (size, sha) -> [Path]
    done = 0
    for lst in candidates:
        size = lst[0].stat().st_size if lst else 0
        # Re-stat defensively (file may have changed mid-scan).
        try:
            size = lst[0].stat().st_size
        except OSError:
            size = -1
        for p in sorted(lst):
            done += 1
            print("hashing %d/%d ..." % (done, to_hash), file=sys.stderr, end="\r")
            digest = sha256_of(p, errors)
            if digest is None:
                skipped += 1
                continue
            try:
                sz = p.stat().st_size
            except OSError:
                skipped += 1
                continue
            by_hash.setdefault((sz, digest), []).append(p)
    print(" " * 40, file=sys.stderr, end="\r")  # clear progress line

    dup_groups = [v for v in by_hash.values() if len(v) > 1]
    dup_groups.sort(key=lambda g: (len(g), str(g[0])))

    if not dup_groups:
        print("scanned %d file(s) (%d hashed); no duplicates." % (total_files, done))
        if skipped or errors:
            print("warning: skipped %d unreadable file(s)." % (skipped), file=sys.stderr)
        print("total reclaimable: 0 bytes.")
        return 0

    total_wasted = 0
    for i, group in enumerate(dup_groups, 1):
        try:
            size = group[0].stat().st_size
        except OSError:
            size = 0
        wasted = size * (len(group) - 1)
        total_wasted += wasted
        print("group %d: %d files x %d bytes (wasted %d bytes)" % (i, len(group), size, wasted))
        for p in sorted(group):
            print("  %s" % p)
    print("total reclaimable: %d bytes in %d group(s)." % (total_wasted, len(dup_groups)))
    if skipped or errors:
        print("warning: skipped %d unreadable file(s)." % skipped, file=sys.stderr)

    # Optional deletion: keep first (sorted) file per group, delete the rest.
    if args.delete:
        # Loud permanent-deletion notice (also in --help).
        print("WARNING: permanently deleting duplicates (no trash)...", file=sys.stderr)
        deleted = 0
        freed = 0
        failed = 0
        for group in dup_groups:
            keep = sorted(group)[0]
            for victim in sorted(group)[1:]:
                try:
                    sz = victim.stat().st_size
                except OSError:
                    sz = 0
                try:
                    # Missing OK guard for races; Windows raises if locked.
                    victim.unlink()
                    deleted += 1
                    freed += sz
                except FileNotFoundError:
                    continue
                except (OSError, PermissionError) as e:
                    print("warning: cannot delete %s: %s" % (victim, e),
                          file=sys.stderr)
                    failed += 1
        print("deleted %d file(s), freed %d bytes%s."
              % (deleted, freed, (" (%d failed)" % failed) if failed else ""))
    else:
        print("tip: re-run with --delete --yes to permanently remove duplicates "
              "(keeps first file per group).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
