#!/bin/bash
# hybrid-fimi-radar — cron cada 6h: captura + análisis
cd /home/miguelc/hybrid-fimi-radar
.venv/bin/python collectors/capture.py --no-analyze >> logs/capture.log 2>&1
.venv/bin/python detection/run_fimi.py --input data/radar.db --db data/radar.db >> logs/fimi.log 2>&1
