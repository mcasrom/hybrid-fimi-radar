#!/bin/bash
cd /home/deploy/hybrid-fimi-radar
.venv/bin/python collectors/capture.py --no-analyze >> logs/capture.log 2>&1
.venv/bin/python detection/run_fimi.py --input data/radar.db --db data/radar.db >> logs/fimi.log 2>&1
