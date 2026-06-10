#!/bin/bash
# Khata landing — build-dashboard server + SRI hash helper.
# The marketing page itself is served by the app at /welcome (src/khata/static/welcome.html).
# Run from repo root:  bash _build-dashboard/verify-and-serve.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo localhost)

# dashboard server :4178
if ! lsof -i :4178 >/dev/null 2>&1; then
  cd "$ROOT/_build-dashboard"
  nohup python3 -m http.server 4178 --bind 0.0.0.0 >/dev/null 2>&1 &
  echo $! > "$ROOT/_build-dashboard/server.pid"
  cd "$ROOT"
fi

echo "🌐 Live build dashboard: http://$IP:4178/dashboard.html"
echo "🌐 Marketing page:       http://$IP:5057/welcome   (served by the app)"
echo
echo "── SRI hashes (already pinned in welcome.html; re-run if bumping CDN versions) ──"
for url in \
  "https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js" \
  "https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/ScrollTrigger.min.js" \
  "https://cdn.jsdelivr.net/npm/lenis@1.1.18/dist/lenis.min.js"; do
  h=$(curl -fsSL "$url" | openssl dgst -sha384 -binary | openssl base64 -A)
  echo "$url"
  echo "  sha384-$h"
done
echo
echo "Kill dashboard server: kill \$(cat _build-dashboard/server.pid)"
