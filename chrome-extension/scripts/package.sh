#!/bin/sh
# Builds dist/youtube-community-<version>.zip for uploading to the Chrome Web Store.
# Only extension files go in; config.js, worker/, scripts/, and docs stay out.
set -e
cd "$(dirname "$0")/.."

if grep -q "YOUR_SUBDOMAIN" endpoints.js; then
  echo "Set WORKER_URL in endpoints.js to your deployed Worker first." >&2
  exit 1
fi

version=$(node -p "require('./manifest.json').version")
out="dist/youtube-community-$version.zip"
mkdir -p dist
rm -f "$out"
zip -q "$out" manifest.json endpoints.js consent.js settings.js background.js youtube.js overlay.js content.js content.css \
  popup.html popup.js welcome.html welcome.js icons/*.png
echo "Built $out"
