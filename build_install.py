#!/usr/bin/env python3
"""Regenerate install.sh from report.py + watchlist.example.json (run after editing either)."""
import hashlib
rp = open('report.py').read(); ex = open('watchlist.example.json').read()
H = hashlib.sha256((rp.rstrip() + '\n').encode()).hexdigest()[:16]
assert 'DEALS_EOF' not in rp + ex
sh = f'''#!/usr/bin/env bash
# Supermarket deal checker installer (Austria). Usage: bash install.sh [DATA_DIR]   (default /workspace/supermarket-deals)
# Writes report.py + watchlist.example.json; creates watchlist.json only if missing; never touches state.json.
set -euo pipefail
DIR="${{1:-${{DEALS_DIR:-/workspace/supermarket-deals}}}}"
command -v curl >/dev/null || {{ echo "curl missing (apt-get install -y curl)"; exit 1; }}
python3 -c 'import sys; sys.exit(sys.version_info < (3,8))' || {{ echo "python3 >= 3.8 required"; exit 1; }}
mkdir -p "$DIR"
cat > "$DIR/report.py" <<'DEALS_EOF'
{rp.rstrip()}
DEALS_EOF
cat > "$DIR/watchlist.example.json" <<'DEALS_EOF'
{ex.rstrip()}
DEALS_EOF
[ -f "$DIR/watchlist.json" ] || cp "$DIR/watchlist.example.json" "$DIR/watchlist.json"
chmod +x "$DIR/report.py"
echo "report.py sha256: $(sha256sum "$DIR/report.py" | cut -c1-16) (expected {H})"
echo "Installed in $DIR. Next: edit $DIR/watchlist.json, then: python3 $DIR/report.py --dir $DIR --seed"
'''
open('install.sh', 'w').write(sh); print(len(sh.encode()), 'bytes')
