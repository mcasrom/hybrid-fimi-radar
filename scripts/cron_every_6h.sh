#!/bin/bash
cd /home/deploy/hybrid-fimi-radar
# 1) Captura: eventos nuevos con su tema (keywords/feeds del config)
.venv/bin/python collectors/capture.py --no-analyze >> logs/capture.log 2>&1
# 2) Detección por TEMA: cada tema activo del catalogo corre su propio pipeline
#    (filtra sus eventos via event_temas y reemplaza su snapshot de clusters).
#    La ausencia de senal en un tema es un resultado valido.
for tema in $(.venv/bin/python -c "import yaml; print(' '.join(yaml.safe_load(open('config.yaml')).get('temas', {}).keys() or ['frontera_sur']))"); do
  echo "=== run_fimi tema=$tema $(date -u +%H:%M) ===" >> logs/fimi.log
  .venv/bin/python detection/run_fimi.py --input data/radar.db --db data/radar.db --tema "$tema" >> logs/fimi.log 2>&1
done
# 3) Dashboard
.venv/bin/python detection/gen_fimi_html.py >> logs/fimi.log 2>&1
# 4) Avisos a suscriptores de Telegram si cambiaron los diales (solo on_change).
#    Sin FIMI_TELEGRAM_BOT_TOKEN no envía nada; idempotente, sin spam.
.venv/bin/python detection/notify_subs_telegram.py >> logs/fimi.log 2>&1
# 4b) Alerta proactiva de salud de fuentes: avisa al dueño SOLO cuando una fuente
#    empeora (activa->baja/inactiva). Estado guardado => sin repeticiones.
.venv/bin/python detection/notify_fuentes.py >> logs/fimi.log 2>&1
# Politica de retencion: conservar solo los ultimos 30 dias de raw JSON
find data/raw -name "*.json" -mtime +30 -delete 2>/dev/null
# Rotar logs mayores de 5MB
for f in logs/*.log; do [ -f "$f" ] && [ $(stat -c%s "$f") -gt 5242880 ] && tail -100 "$f" > "$f.tmp" && mv "$f.tmp" "$f"; done

# 5) Mantenimiento: retencion 90d (events/findings) + VACUUM + backup BD rotado a 4
.venv/bin/python detection/mantenimiento.py >> logs/mantenimiento.log 2>&1

# 6) Checklist de promocion: ventana de validacion de politica_nacional (piloto).
#    Al cumplir 72h sin errores avisa por Telegram para pasar el tema a produccion.
.venv/bin/python detection/check_promocion.py >> logs/promocion.log 2>&1
