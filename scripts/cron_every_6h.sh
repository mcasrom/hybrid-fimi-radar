#!/bin/bash
cd /home/deploy/hybrid-fimi-radar
# 1) Captura: eventos nuevos con su tema (keywords/feeds del config)
.venv/bin/python collectors/capture.py --no-analyze >> logs/capture.log 2>&1
# 2) Detección por TEMA: cada tema ACTIVO del catálogo corre su propio pipeline
#    (filtra sus eventos via event_temas y reemplaza su snapshot de clusters).
#    Se salta los temas cerrados (estado != produccion|piloto) — su pipeline se
#    detiene al cerrarlos con temas_cli.py, y los datos quedan exportados.
#    La ausencia de senal en un tema es un resultado valido.
for tema in $(.venv/bin/python -c "
import yaml
c = yaml.safe_load(open('config.yaml'))
temas = c.get('temas', {}) or {}
print(' '.join(t for t, m in temas.items() if m.get('estado', 'produccion') in ('produccion', 'piloto')))
"); do
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

# 7) Candidatos a cierre (solo avisa, NO decide): si un tema activo lleva señal
#    débil sostenida (volumen bajo + 0 narrativas sostenidas, o piloto >90d),
#    notifica al dueño por Telegram y registra una sugerencia en la bitácora.
.venv/bin/python detection/check_cierre.py >> logs/cierre.log 2>&1

# 8) Alerta de ingesta: si la captura lleva >7.5h sin actualizar (se saltó un
#    ciclo del cron cada 6h), avisa al dueño por Telegram una vez por episodio.
.venv/bin/python detection/check_ingesta.py >> logs/ingesta.log 2>&1

# 9) Salud de keywords por tema: detecta el patrón "tema ciego" (keywords de
#    registro metodológico que los titulares reales no usan -> el tema apenas
#    ve su ruido real). Persiste estado en data/salud_keywords.json; avisa por
#    Telegram SOLO cuando un tema entra en alerta (data/keywords_estado.json).
.venv/bin/python detection/salud_keywords.py --save --notify >> logs/salud_keywords.log 2>&1

# 10) Check médico integral: salud estructural del pipeline (frescura captura,
#     snapshots por tema, integridad BD, coherencia config). Avisa por Telegram
#     cuando el nivel global empeora (data/sistema_estado.json).
.venv/bin/python detection/check_sistema.py --notify >> logs/sistema.log 2>&1
