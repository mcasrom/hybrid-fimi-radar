#!/bin/bash
# Backup offsite de configuración y bitácora del radar FIMI.
# Se ejecuta semanalmente (domingo 03:00) para tener copia fuera del server.
# Uso: cp a ~/Desktop/demo/backup_offsite/ (sincronizable con repo demo local).
set -euo pipefail

FIMI_DIR="/home/deploy/hybrid-fimi-radar"
DEST_DIR="/home/deploy/hybrid-fimi-radar/backups/offsite"
KEEP=4

mkdir -p "$DEST_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M)

# Copiar config.yaml + bitácora (datos de gobernanza)
cp "$FIMI_DIR/config.yaml" "$DEST_DIR/config_${TIMESTAMP}.yaml"
cp "$FIMI_DIR/data/bitacora.db" "$DEST_DIR/bitacora_${TIMESTAMP}.db" 2>/dev/null || echo "[backup] bitacora.db no existe (pendiente)"

# Rotar: mantener solo los KEEP más recientes
cd "$DEST_DIR"
ls -1t config_*.yaml 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
ls -1t bitacora_*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --

echo "[backup-offsite] ${TIMESTAMP} creado ($(du -sh "$DEST_DIR" | cut -f1))"
