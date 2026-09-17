# RUNBOOK — Radar FIMI

Guía de **operación, despliegue y recuperación**. Escrita para que otra persona
pueda mantener el radar sin conocimiento previo (mitiga el **bus factor 1**).

---

## 1. Dónde vive todo

| Qué | Dónde |
|---|---|
| Servidor | Hetzner `178.105.80.193` (usuario `deploy`, SSH por clave) |
| Código | `~/hybrid-fimi-radar` en el server · GitHub `mcasrom/hybrid-fimi-radar` (público, AGPL-3.0) |
| Entorno Python | `~/hybrid-fimi-radar/.venv` → usar SIEMPRE `.venv/bin/python` |
| Base de datos | `data/radar.db` (SQLite, chmod 600) |
| Config | `config.yaml` (feeds, temas, keywords, scoring) + `.env` (tokens, chmod 600) |
| Dashboard | `/var/www/fimi/index.html` + `research.html` (estático, **generado**) |
| Páginas estáticas | `/var/www/fimi/{api,admin,operativa}.html` (NO en repo) |
| nginx | `/etc/nginx/sites-enabled/fimi.viajeinteligencia.com` |
| Backups BD | `backups/radar-*.db.gz` (rotación 4) |
| Backup offsite | `backups/offsite/` (config + bitácora, semanal) |
| Logs | `logs/*.log` |
| Zona Cloudflare | `a56f7c002b1db64082f0813b839db412` (viajeinteligencia.com) |

---

## 2. El pipeline (cada 6 h)

`scripts/cron_every_6h.sh` (cron `30 */6 * * *`) es el **único orquestador**:

1. **Captura** (`collectors/capture.py`): RSS + Telegram + Reddit + bluesky/google-news/mastodon. Deduplica (UNIQUE) y descarta eventos >90 d.
2. **Detección por tema** (`detection/run_fimi.py --tema X`): itera los temas `produccion|piloto`; cada uno filtra sus eventos (`event_temas`), calcula features → coordinación → clustering, puntúa y **reemplaza su snapshot** de clusters.
3. **Dashboard** (`detection/gen_fimi_html.py`): genera `/var/www/fimi/index.html` + `research.html`.
4. **Avisos** Telegram on_change (`notify_subs_telegram.py`) + salud de fuentes (`notify_fuentes.py`).
5. **Mantenimiento** (`detection/mantenimiento.py`): retención 90 d + VACUUM (solo si hubo purgas) + backup BD (rotación 4).
6-10. **Checks**: promoción de pilotos, candidatos a cierre, ingesta saltada, salud de keywords, check médico (`check_sistema.py`).

**Crons auxiliares FIMI** (en el crontab de `deploy`):

| Cuándo | Qué |
|---|---|
| `0 9 * * 1` | Digest email semanal (`email_digest.py`) |
| `15 7 * * 1` | Validación externa EUvsDisinfo (`validacion_auto.py --notify`) |
| `0 8 1 * *` | Validación curada: muestra nueva + historial (`validacion_curada_auto.py --notify`) |
| `30 7 * * 0` | Restore-test del backup (`restore_test.py`) |
| `0 3 * * 0` | Backup offsite (`backup_offsite.sh`) |

---

## 3. Tareas frecuentes

### Añadir un tema
```bash
.venv/bin/python detection/temas_cli.py alta <slug> --nombre "..." --keywords "a,b,c" --verifica
```
Alta en **PILOTO** (el `filtro` gatea el contenido; `--verifica` simula cobertura).
Cerrar: `temas_cli.py cerrar <slug> --nota "..."` (exporta evidencia a `data/export/`).

### Añadir / editar un feed
Editar el bloque `feeds:` de `config.yaml`; documentar `bias`, `reliability`,
`transparency`, `analytical_relevance`; verificar **HTTP 200 con UA de navegador**.

### Regenerar el dashboard a mano
```bash
cd ~/hybrid-fimi-radar && .venv/bin/python detection/gen_fimi_html.py
```
⚠️ Tras CADA regen manual → **purgar Cloudflare** (`purge_everything`) ANTES de decir "ya está".

### Etiquetar la validación curada
Bot Telegram → **`/validar`** (2 toques por cluster, solo el admin `FIMI_OWNER_CHAT`).

### Desplegar un cambio de código
`git pull` en el server (o `scp`), `py_compile`, y dejar que el siguiente cron aplique.
Si toca el dashboard, regenerar + purgar CF. Commit en español + `git push origin main`.

---

## 4. Observabilidad

- **Check médico**: `.venv/bin/python detection/check_sistema.py` → `nivel: ok|warn|bad`.
- **PM2**: `pm2 list` (apps FIMI: `radar-email-api`, `radar-fimi-bot`).
- **Logs**: `logs/{capture,fimi,mantenimiento,promocion,cierre,ingesta,salud_keywords,sistema}.log`.
- **API**: `curl http://127.0.0.1:3311/api/health`.

---

## 5. Recuperación

- **Restore-test** (no toca prod): `.venv/bin/python detection/restore_test.py`.
- **Restaurar de verdad**: parar el cron → descomprimir `backups/radar-YYYYMMDD*.db.gz`
  → `data/radar.db` → reanudar.
- **Reconstruir desde cero**: clonar el repo + restaurar `config.yaml` y la BD desde
  `backups/offsite/`. El pipeline se repuebla solo en el siguiente ciclo.

---

## 6. Incidencias conocidas

- **OOM**: el pico de `run_fimi frontera_sur` crece con el corpus (~7,5 KB/evento;
  OOM estimado ~298k events). `check_sistema` avisa al cruzar 250k / 290k.
- **nginx + hostname en upstream**: se resuelve en tiempo de carga → si el DNS tarda,
  nginx no arranca. Solución: variable + `resolver` (DNS diferido a la petición).
- **Cloudflare**: verificar el dashboard con **UA de navegador** (curl recibe 444/520 por el bot-block).
- **`cluster_label` no es estable** entre ciclos (se regenera): no usarlo como ID persistente.

---

## 7. Continuidad (bus factor 1)

Para retomar el proyecto basta con: (1) acceso SSH al server; (2) **este runbook**;
(3) `docs/` (`SCORING`, `TAXONOMIA`, `FUENTES`, `GOBERNANZA`, `ATRIBUCION-LIMITACIONES`,
`TRAZABILIDAD`); (4) `README.md`; (5) la **bitácora** (`data/bitacora.db`), que registra
toda decisión de estado con fecha, motivo y origen.
