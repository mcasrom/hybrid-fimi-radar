#!/bin/bash
cd /home/deploy/hybrid-fimi-radar
.venv/bin/python collectors/capture.py --no-analyze >> logs/capture.log 2>&1
.venv/bin/python detection/run_fimi.py --input data/radar.db --db data/radar.db >> logs/fimi.log 2>&1
.venv/bin/python detection/gen_fimi_html.py >> logs/fimi.log 2>&1
# Politica de retencion: conservar solo los ultimos 30 dias de raw JSON
find data/raw -name "*.json" -mtime +30 -delete 2>/dev/null
# Rotar logs mayores de 5MB
for f in logs/*.log; do [ -f "$f" ] && [ $(stat -c%s "$f") -gt 5242880 ] && tail -100 "$f" > "$f.tmp" && mv "$f.tmp" "$f"; done
