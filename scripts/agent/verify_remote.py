#!/usr/bin/env python3
"""Compare local git blob SHAs with a remote GitHub directory listing or commit file list.

Agent tooling. Feed it the JSON text returned by the GitHub MCP `get_file_contents` (directory listing: list of entries
with `path` and `sha`). Prints MATCH / DIFF / MISSING-LOCAL for every remote file entry and exits non-zero on any DIFF.

Usage: python3 scripts/agent/verify_remote.py listing.json [listing2.json ...]
The listing file may be the raw MCP tool result; the first JSON array found inside it is used.
"""
import json
import os
import re
import subprocess
import sys


def blob_sha(path):
    return subprocess.run(["git", "hash-object", path], check=True, capture_output=True, text=True).stdout.strip()


def extract_entries(text):
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = None
    # unwrap MCP envelopes: {"content":[{"type":"text","text":"[...]"}]}
    for _ in range(4):
        if isinstance(obj, dict) and "content" in obj and isinstance(obj["content"], list):
            obj = json.loads(obj["content"][0]["text"])
        elif isinstance(obj, str):
            obj = json.loads(obj)
        else:
            break
    if isinstance(obj, list):
        return obj
    m = re.search(r"\[\{.*\}\]", text, re.S)
    if not m:
        raise SystemExit("no listing found")
    return json.loads(m.group(0))


def main():
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True,
                          text=True).stdout.strip()
    bad = 0
    for fn in sys.argv[1:]:
        with open(fn, encoding="utf-8") as fh:
            entries = extract_entries(fh.read())
        for e in entries:
            if e.get("type") != "file":
                print(f"DIR      {e.get('path')}")
                continue
            p = os.path.join(root, e["path"])
            if not os.path.exists(p):
                print(f"MISSING-LOCAL {e['path']}")
                continue
            local = blob_sha(p)
            status = "MATCH" if local == e["sha"] else "DIFF"
            bad += status != "MATCH"
            print(f"{status:8} {e['path']}  remote={e['sha'][:12]} local={local[:12]}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
