#!/usr/bin/env python3
"""detection/vigilancia_narrativa.py — observación intensa de narrativas.

Cuenta, por ciclo, los eventos que coinciden con una narrativa (términos requeridos
+ contexto) sobre la BD viva y avisa por Telegram si hay ESCALADA respecto a la
última ejecución. Pensado para vigilar p. ej. "drones (Marruecos) sobre Ceuta/Melilla".

Diseño:
  - Solo LEE (`events`, `event_temas`, `cluster_events`); no toca score/bandas.
  - Prefiltro SQL barato (LIKE por el término más genérico) + normalización compartida.
  - Estado en `data/vigilancia_estado.json` (id -> {ultimo_conteo, historial}).
  - Notificación opcional (`--notify`) por Telegram (FIMI_TELEGRAM_BOT_TOKEN/-OWNER_CHAT).

CLI:
    python detection/vigilancia_narrativa.py            # JSON a stdout
    python detection/vigilancia_narrativa.py --notify   # avisa por Telegram si escala
    python detection/vigilancia_narrativa.py --json
    python detection/vigilancia_narrativa.py --dry      # no escribe estado ni notifica
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from normalizer.clasificar import normalizar  # noqa: E402

DB = ROOT / "data" / "radar.db"
STATE = ROOT / "data" / "vigilancia_estado.json"
LOG = ROOT / "logs" / "vigilancia.log"

DEFAULTS = {"ventana_horas": 48, "factor_escalada": 1.5, "delta_escalada": 10, "narrativas": []}


def _cfg(cfg):
    v = dict(DEFAULTS)
    v.update((cfg or {}).get("vigilancia", {}) or {})
    return v


def _load_cfg(path=None):
    import yaml
    p = Path(path) if path else (ROOT / "config.yaml")
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[warn] vigilancia: config ({e})", file=sys.stderr)
        return {}


def _load_env():
    """Carga ROOT/.env en os.environ (para cron: token/chat de Telegram)."""
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception as e:
        print(f"[warn] vigilancia: no pude leer .env ({e})", file=sys.stderr)


def _load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st):
    try:
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[warn] vigilancia: no pude guardar estado ({e})", file=sys.stderr)


def evaluar_escalada(prev, cur, factor=1.5, delta=10):
    """Pura: ¿el conteo actual es una escalada respecto al previo?

    Escala si hay subida absoluta grande (>= delta) O relativa grande (>= factor).
    """
    if prev is None:
        return False
    if cur - prev >= delta:
        return True
    if prev > 0 and cur >= prev * factor:
        return True
    return False


def contar(con, narrativa, ventana_horas, ahora=None):
    """Cuenta eventos de una narrativa (requeridos + contexto) en la ventana."""
    ahora = ahora or int(time.time())
    desde = ahora - int(ventana_horas) * 3600
    req = [normalizar(x) for x in (narrativa.get("requeridos") or []) if x]
    ctx = [normalizar(x) for x in (narrativa.get("contexto") or []) if x]
    if not req:
        return {"n": 0, "redes": 0, "rss": 0, "cuentas": 0, "urls": 0, "temas": {}}
    # prefiltro SQL barato por el término más largo (más específico)
    pref = max(req, key=len)
    q = ("SELECT id, source, author, url, tema_id, text, title FROM events"
         " WHERE timestamp >= ? AND (lower(text) LIKE ? OR lower(title) LIKE ?)")
    like = f"%{pref}%"
    n = redes = rss = 0
    cuentas, urls, temas = set(), set(), {}
    for r in con.execute(q, (desde, like, like)):
        txt = normalizar((r["text"] or "") + " " + (r["title"] or ""))
        if not any(t in txt for t in req):
            continue
        if ctx and not any(c in txt for c in ctx):
            continue
        n += 1
        if str(r["source"] or "").startswith("rss"):
            rss += 1
        else:
            redes += 1
        if r["author"]:
            cuentas.add(r["author"])
        if r["url"]:
            urls.add(r["url"])
        t = r["tema_id"] or "?"
        temas[t] = temas.get(t, 0) + 1
    return {"n": n, "redes": redes, "rss": rss, "cuentas": len(cuentas),
            "urls": len(urls), "temas": temas}


def _notify(text):
    token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("FIMI_OWNER_CHAT", "")
    if not token or not chat:
        print("[warn] vigilancia: sin Telegram token/chat", file=sys.stderr)
        return False
    try:
        import requests
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text, "parse_mode": "HTML"},
                          timeout=20)
        return r.status_code == 200
    except Exception as e:
        print(f"[warn] vigilancia: Telegram ({e})", file=sys.stderr)
        return False


def run(cfg=None, db=None, notify=False, dry=False):
    _load_env()
    cfg = cfg or _load_cfg()
    v = _cfg(cfg)
    st = _load_state()
    con = sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = []
    try:
        for nar in v["narrativas"]:
            nid = nar.get("id") or nar.get("nombre") or "?"
            res = contar(con, nar, v["ventana_horas"])
            prev = (st.get(nid) or {}).get("ultimo_conteo")
            esc = evaluar_escalada(prev, res["n"], v["factor_escalada"], v["delta_escalada"])
            res.update({"id": nid, "nombre": nar.get("nombre", nid),
                        "conteo_previo": prev, "escalada": esc})
            out.append(res)
            if not dry:
                h = (st.get(nid) or {}).get("historial", [])
                h = (h + [{"ts": int(time.time()), "n": res["n"]}])[-30:]
                st[nid] = {"ultimo_conteo": res["n"], "historial": h, "nombre": nar.get("nombre", nid)}
            if notify and esc:
                msg = (f"🚨 <b>Escalada</b> · {res['nombre']}\n"
                       f"{res['n']} eventos ({res['redes']} redes/{res['rss']} rss) · "
                       f"previo {prev}\ncuentas {res['cuentas']} · urls {res['urls']}")
                _notify(msg)
    finally:
        con.close()
    if not dry:
        _save_state(st)
    return out


def main():
    ap = argparse.ArgumentParser(description="Vigilancia de narrativas (observación intensa).")
    ap.add_argument("--config", default=None)
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    out = run(_load_cfg(args.config), db=args.db, notify=args.notify, dry=args.dry)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not args.dry:
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": int(time.time()), "res": out}, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[warn] vigilancia: log ({e})", file=sys.stderr)


if __name__ == "__main__":
    main()
