#!/bin/bash
# measure_rss.sh — mide el pico RSS (VmHWM) y el tiempo por tema, como el cron.
cd /home/deploy/hybrid-fimi-radar || exit 1
: > logs/fimi_rss.log
for tv in $(.venv/bin/python -c "
import yaml
c = yaml.safe_load(open('config.yaml'))
for t, m in (c.get('temas') or {}).items():
    m = m or {}
    if m.get('estado', 'produccion') in ('produccion', 'piloto'):
        print('%s:%d' % (t, int(m.get('ventana_dias', 45))))
"); do
  tema="${tv%%:*}"; vent="${tv##*:}"
  /usr/bin/time -a -o logs/fimi_rss.log -f "run tema=$tema ventana=${vent}d: %e s  %M KB RSS" \
    .venv/bin/python detection/run_fimi.py --input data/radar.db --db data/radar.db \
    --tema "$tema" --ventana-dias "$vent" >> logs/fimi.log 2>&1
done
echo "MEASURE_DONE $(date -u +%H:%M)" >> logs/fimi_rss.log
