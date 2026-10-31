#!/usr/bin/env bash
# Roblox-side static checks (T-0012/T-0013): Rojo build of the place + strict type check of every Roblox script against
# the Roblox API definitions (luau-lsp). Downloads pinned tools into .tools/ on first use (Linux x86_64 or macOS).
# Usage: scripts/check_roblox.sh [output.rbxlx]      (default output: build/RlpsDemo.rbxlx)
set -euo pipefail
cd "$(dirname "$0")/.."
ROJO_VERSION=7.7.1
LSP_VERSION=1.70.1
TOOLS=.tools
OUT=${1:-build/RlpsDemo.rbxlx}
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) ROJO_ASSET=linux-x86_64; LSP_ASSET=linux-x86_64 ;;
  Darwin-*) ROJO_ASSET=macos-$(uname -m | sed 's/arm64/aarch64/'); LSP_ASSET=macos ;;
  *) echo "unsupported platform; install rojo $ROJO_VERSION and luau-lsp $LSP_VERSION manually into $TOOLS/" >&2; exit 2 ;;
esac
mkdir -p "$TOOLS" "$(dirname "$OUT")"
if [ ! -x "$TOOLS/rojo" ]; then
  curl -fsSL -o "$TOOLS/rojo.zip" "https://github.com/rojo-rbx/rojo/releases/download/v$ROJO_VERSION/rojo-$ROJO_VERSION-$ROJO_ASSET.zip"
  unzip -oq "$TOOLS/rojo.zip" -d "$TOOLS" && chmod +x "$TOOLS/rojo"
fi
if [ ! -x "$TOOLS/luau-lsp" ]; then
  curl -fsSL -o "$TOOLS/lsp.zip" "https://github.com/JohnnyMorganz/luau-lsp/releases/download/$LSP_VERSION/luau-lsp-$LSP_ASSET.zip"
  unzip -oq "$TOOLS/lsp.zip" -d "$TOOLS" && chmod +x "$TOOLS/luau-lsp"
fi
if [ ! -f "$TOOLS/globalTypes.d.luau" ]; then
  curl -fsSL -o "$TOOLS/globalTypes.d.luau" \
    "https://raw.githubusercontent.com/JohnnyMorganz/luau-lsp/$LSP_VERSION/scripts/globalTypes.d.luau"
fi
"$TOOLS/rojo" build default.project.json -o "$OUT"
"$TOOLS/rojo" sourcemap default.project.json -o "$TOOLS/sourcemap.json"
LOG=$("$TOOLS/luau-lsp" analyze --platform=roblox --definitions=@roblox="$TOOLS/globalTypes.d.luau" \
  --sourcemap="$TOOLS/sourcemap.json" roblox/src 2>&1 | grep -v '^\[INFO\]\|didChangeWatchedFiles' || true)
if [ -n "$LOG" ]; then
  echo "$LOG"
  echo "luau-lsp analyze (Roblox definitions): FAIL" >&2
  exit 1
fi
echo "luau-lsp analyze (Roblox definitions, roblox/src): OK"
