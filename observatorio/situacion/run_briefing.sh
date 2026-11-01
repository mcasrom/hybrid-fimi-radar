#!/usr/bin/env bash
set -euo pipefail
BASE=/home/deploy/observatorio-static/situacion
OUT=/var/www/fimi/observatorio/ceuta/situacion/cambios/index.html
/usr/bin/python3 "$BASE/gen_briefing.py" \
  --situacion "$BASE/situacion_frontera_sur.json" \
  --snapshots "$BASE/snapshots" \
  --out "$OUT"
/usr/bin/python3 /home/deploy/observatorio/apply_header.py
