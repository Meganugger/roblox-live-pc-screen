#!/usr/bin/env python3
"""Build a GitHub MCP `push_files` arguments JSON from local files.

Agent tooling (not part of the runtime system). The agent environment used for this project has no git credentials;
commits are created through the GitHub MCP `push_files` tool, which accepts an arguments file. This script turns a set
of local paths into that arguments object so file contents never need to be pasted by hand.

Usage:
  python3 scripts/agent/make_push_payload.py -m "commit message" -o /tmp/payload.json [--all | path ...]

--all  : every git-tracked + untracked-but-not-ignored text file in the working tree.
Binary files are refused (push_files only carries text). Max output size 1 MiB (tool limit) – split commits if needed.
"""
import argparse
import json
import os
import subprocess
import sys

OWNER = "Meganugger"
REPO = "roblox-live-pc-screen"
BRANCH = "main"
LIMIT = 1024 * 1024


def list_all(root):
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=root, check=True, capture_output=True, text=True).stdout
    return sorted({p for p in out.splitlines() if p and os.path.isfile(os.path.join(root, p))})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", required=True)
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--branch", default=BRANCH)
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True,
                          text=True).stdout.strip()
    paths = list_all(root) if a.all else sorted(set(a.paths))
    if not paths:
        sys.exit("no files selected")
    files = []
    for p in paths:
        full = os.path.join(root, p)
        with open(full, "rb") as fh:
            raw = fh.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            sys.exit(f"refusing binary/non-UTF-8 file: {p}")
        files.append({"path": p.replace(os.sep, "/"), "content": text})
    payload = {"owner": OWNER, "repo": REPO, "branch": a.branch, "message": a.message, "files": files}
    data = json.dumps(payload, ensure_ascii=False)
    if len(data.encode("utf-8")) > LIMIT:
        sys.exit(f"payload {len(data)} bytes exceeds 1 MiB; split into several commits")
    with open(a.output, "w", encoding="utf-8") as fh:
        fh.write(data)
    print(f"{len(files)} files, {len(data.encode('utf-8'))} bytes -> {a.output}")
    for f in files:
        print("  ", f["path"])


if __name__ == "__main__":
    main()
