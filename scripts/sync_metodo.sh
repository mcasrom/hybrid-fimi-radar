#!/usr/bin/env bash
# sync_metodo.sh — mantiene docs/metodo.html (versionado) y /var/www/fimi/metodo.html (servido).
#
# Uso:
#   scripts/sync_metodo.sh                    # docs -> servido (con backup)
#   scripts/sync_metodo.sh --from-served      # servido -> docs (para versionar cambios hechos en el servidor)
#   scripts/sync_metodo.sh --check            # solo compara; rc=0 si iguales, 1 si difieren
#
# Tras cambiar el servido: purgar Cloudflare (bash demo/cf_purge.sh fimi) y commitear docs/metodo.html.
set -euo pipefail

ROOT="/home/deploy/hybrid-fimi-radar"
SRC="$ROOT/docs/metodo.html"
DST="/var/www/fimi/metodo.html"
MODE="${1:-to-served}"

if [ ! -f "$SRC" ] || [ ! -f "$DST" ]; then
  echo "Falta $SRC o $DST" >&2
  exit 2
fi

if cmp -s "$SRC" "$DST"; then
  echo "Sincronizados: docs/metodo.html == /var/www/fimi/metodo.html"
  exit 0
fi

case "$MODE" in
  --check)
    echo "DIFERENCIAS (servido vs docs):" >&2
    diff -u "$DST" "$SRC" | head -40 >&2 || true
    exit 1
    ;;
  --from-served)
    bk="$SRC.bak-sync-$(date -u +%Y%m%d%H%M%S)"
    cp -a "$SRC" "$bk"
    cp -a "$DST" "$SRC"
    echo "Copiado servido -> docs (backup $bk)"
    echo "Ahora: git add docs/metodo.html && git commit && git push; y purga CF."
    ;;
  to-served|"")
    bk="$DST.bak-sync-$(date -u +%Y%m%d%H%M%S)"
    cp -a "$DST" "$bk"
    cp -a "$SRC" "$DST"
    echo "Copiado docs -> servido (backup $bk)"
    echo "Purga CF: bash demo/cf_purge.sh fimi"
    ;;
  *)
    echo "Uso: $0 [--check|--from-served]" >&2
    exit 2
    ;;
esac
