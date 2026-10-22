#!/bin/sh
# Transfer installer for macOS:  curl -fsSL https://raw.githubusercontent.com/sharmashivesh6/transfer/main/install.sh | sh
# Downloading with curl (not a browser) means macOS doesn't quarantine the app, so it opens without the security prompt.
set -e
[ "$(uname -m)" = arm64 ] || { echo "Sorry, Transfer needs a Mac with Apple Silicon (M1 or newer)."; exit 1; }
DEST="${DEST:-/Applications}"
[ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
TMP=$(mktemp -d)
echo "Downloading Transfer..."
curl -fL --progress-bar -o "$TMP/Transfer.zip" https://github.com/sharmashivesh6/transfer/releases/latest/download/Transfer-mac.zip
pkill -x Transfer 2>/dev/null || true  # replace a running copy
rm -rf "$DEST/Transfer.app"
ditto -x -k "$TMP/Transfer.zip" "$DEST"
rm -rf "$TMP"
open "$DEST/Transfer.app"
echo "Done. Transfer is in $DEST and is now open."
