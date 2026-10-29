#!/usr/bin/env python3
"""Auditoría determinista de FIMI. Read-only, sin IA y sin coste.

Comprueba:
- catálogo activo/congelado;
- cuadre event_temas/clusters/cluster_events;
- huérfanos, duplicados, timestamps futuros y URLs vacías;
- estabilidad de temas congelados entre ejecuciones;
- API pública por tema;
- muestra de URLs de temas activos.

Salida: /home/deploy/auditorias/audit_YYYYMMDD_HHMMSS.{json,md}
Exit 1 si hay fallo crítico.
"""
from __future__ import annotations
import argparse, hashlib, json, sqlite3, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/deploy/hybrid-fimi-radar")
DB = ROOT / "data" / "radar.db"
CFG = ROOT / "config.yaml"
OUT = Path("/home/deploy/auditorias")
STATE = ROOT / "data" / "audit_frozen_state.json"
API = "http://127.0.0.1:3311"
UA = "Mozilla/5.0 (compatible; fimi-audit/1.0)"
ACTIVE = {"produccion", "piloto"}
CRIT = []
WARN = []


def _cfg():
    import yaml
    return yaml.safe_load(CFG.read_text(encoding="utf-8")) or {}


def _db():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _get(url, timeout=15, attempts=2):
    last = None
    for i in range(attempts):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.geturl()
        except Exception as e:
            last = str(e)
            time.sleep(1 + i)
    return None, last


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def audit(sample_urls=5):
    cfg = _cfg()
    temas = cfg.get("temas", {}) or {}
    active = [t for t, m in temas.items() if (m or {}).get("estado", "produccion") in ACTIVE]
    frozen = [t for t, m in temas.items() if (m or {}).get("estado") not in ACTIVE]
    con = _db()
    now = int(time.time())
    result = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "active": active, "frozen": frozen, "db": {}, "api": {}, "urls": {}, "checks": []}
    # cuadre / integridad
    for t in active + frozen:
        ev = con.execute("SELECT COUNT(*) FROM event_temas WHERE tema_id=?", (t,)).fetchone()[0]
        cl = con.execute("SELECT COUNT(*) FROM clusters WHERE tema_id=?", (t,)).fetchone()[0]
        ce = con.execute("SELECT COUNT(*) FROM cluster_events ce JOIN clusters c ON c.id=ce.cluster_id WHERE c.tema_id=?", (t,)).fetchone()[0]
        au = con.execute("SELECT COUNT(DISTINCT ce.author) FROM cluster_events ce JOIN clusters c ON c.id=ce.cluster_id WHERE c.tema_id=?", (t,)).fetchone()[0]
        result["db"][t] = {"event_temas": ev, "clusters": cl, "cluster_events": ce, "accounts": au}
    for name, sql in {
        "orphan_event_temas": "SELECT COUNT(*) FROM event_temas et LEFT JOIN events e ON e.id=et.event_id WHERE e.id IS NULL",
        "orphan_cluster_events": "SELECT COUNT(*) FROM cluster_events ce LEFT JOIN clusters c ON c.id=ce.cluster_id WHERE c.id IS NULL",
        "future_events": "SELECT COUNT(*) FROM events WHERE timestamp > ?",
        "empty_url_active": "SELECT COUNT(*) FROM events e JOIN event_temas et ON et.event_id=e.id WHERE et.tema_id IN (%s) AND (e.url IS NULL OR TRIM(e.url)='') AND (e.bsky_uri IS NULL OR TRIM(e.bsky_uri)='')" % ",".join("?"*len(active)),
        "empty_url_with_bsky": "SELECT COUNT(*) FROM events e JOIN event_temas et ON et.event_id=e.id WHERE et.tema_id IN (%s) AND (e.url IS NULL OR TRIM(e.url)='') AND e.bsky_uri IS NOT NULL AND TRIM(e.bsky_uri)<>''" % ",".join("?"*len(active)),
        "empty_url_by_source": "SELECT e.source, COUNT(*) n FROM events e JOIN event_temas et ON et.event_id=e.id WHERE et.tema_id IN (%s) AND (e.url IS NULL OR TRIM(e.url)='') AND (e.bsky_uri IS NULL OR TRIM(e.bsky_uri)='') GROUP BY e.source ORDER BY n DESC" % ",".join("?"*len(active)),
    }.items():
        try:
            if name == "empty_url_by_source":
                result["db"][name] = [dict(r) for r in con.execute(sql, tuple(active)).fetchall()]
                continue
            args = (now + 3600,) if name == "future_events" else (tuple(active) if name in ("empty_url_active", "empty_url_with_bsky") else ())
            val = con.execute(sql, args).fetchone()[0]
            result["db"][name] = val
        except Exception as e:
            WARN.append(f"{name}: {e}")
    # duplicados de URL (solo aviso; no toda repetición es error)
    dup = con.execute("SELECT COUNT(*) FROM (SELECT url FROM events WHERE url IS NOT NULL AND TRIM(url)<>'' GROUP BY url HAVING COUNT(*)>1)").fetchone()[0]
    result["db"]["duplicate_urls"] = dup
    _total_active = sum(result["db"][t]["event_temas"] for t in active)
    _sin = result["db"].get("empty_url_active", 0)
    result["db"]["empty_url_ratio_pct"] = round(100 * _sin / max(1, _total_active), 1)
    if result["db"]["empty_url_ratio_pct"] > 10:
        CRIT.append("demasiados eventos sin URL ni URI (>10 %)")
    elif result["db"]["empty_url_ratio_pct"] > 5:
        WARN.append(f"eventos sin URL ni URI: {_sin} ({result['db']['empty_url_ratio_pct']} %)")
    # huérfanos/futuro son críticos
    if result["db"].get("orphan_event_temas"):
        CRIT.append("event_temas huérfanos")
    if result["db"].get("orphan_cluster_events"):
        CRIT.append("cluster_events huérfanos")
    if result["db"].get("future_events"):
        CRIT.append("eventos con timestamp futuro")
    # congelados: comparar con estado previo
    prev = {}
    if STATE.exists():
        try: prev = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception: prev = {}
    cur_frozen = {t: {"event_temas": result["db"][t]["event_temas"],
                      "clusters": result["db"][t]["clusters"]} for t in frozen}
    for t, v in cur_frozen.items():
        p = prev.get(t)
        if p and (p.get("event_temas") != v["event_temas"] or p.get("clusters") != v["clusters"]):
            CRIT.append(f"tema congelado cambió: {t}")
    STATE.write_text(json.dumps(cur_frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # API
    for t in active + frozen:
        code, url = _get(f"{API}/api/v1/tema/{t}", timeout=20, attempts=1)
        result["api"][t] = {"status": code, "url": url}
        if code == 404:
            CRIT.append(f"API {t}: 404")
        elif code != 200:
            WARN.append(f"API {t}: {code or 'sin respuesta'} ({url})")
    # URLs muestra de activos
    for t in active:
        rows = con.execute(
            "SELECT DISTINCT e.url FROM events e JOIN event_temas et ON et.event_id=e.id "
            "WHERE et.tema_id=? AND e.url IS NOT NULL AND TRIM(e.url)<>'' LIMIT ?",
            (t, sample_urls)).fetchall()
        checks = []
        for r in rows:
            code, final = _get(r["url"], timeout=10)
            checks.append({"url": r["url"], "status": code, "final": final})
            if code is None or code >= 500:
                WARN.append(f"URL no comprobable en {t}: {r['url']} ({final})")
        result["urls"][t] = checks
    con.close()
    result["critical"] = CRIT
    result["warnings"] = WARN
    return result


def render(res):
    lines = [f"# Auditoría FIMI — {res['generated_utc']}", ""]
    lines += [f"**Activos:** {', '.join(res['active']) or '—'}", ""]
    lines += [f"**Congelados:** {', '.join(res['frozen']) or '—'}", ""]
    lines += ["## Integridad", "", "| Comprobación | Valor |", "|---|---:|"]
    for k in ("orphan_event_temas", "orphan_cluster_events", "future_events", "empty_url_active", "empty_url_with_bsky", "empty_url_ratio_pct", "duplicate_urls"):
        lines.append(f"| {k} | {res['db'].get(k, '—')} |")
    src = res["db"].get("empty_url_by_source") or []
    lines += ["", "### Eventos sin URL ni URI por fuente", "", "| Fuente | N |", "|---|---:|"]
    for row in src:
        lines.append(f"| {row['source']} | {row['n']} |")
    lines += ["", "## Temas", "", "| Tema | Eventos | Clusters | Cuentas |", "|---|---:|---:|---:|"]
    for t, v in res["db"].items():
        if isinstance(v, dict):
            lines.append(f"| {t} | {v['event_temas']} | {v['clusters']} | {v['accounts']} |")
    lines += ["", "## API", "", "| Tema | HTTP |", "|---|---:|"]
    for t, v in res["api"].items():
        lines.append(f"| {t} | {v['status']} |")
    lines += ["", "## Resultado", ""]
    lines += [f"- **Crítico:** {', '.join(res['critical']) or 'ninguno'}",
              f"- **Avisos:** {len(res['warnings'])}"]
    if res["warnings"]:
        lines += [f"  - {w}" for w in res["warnings"][:20]]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = audit(a.urls)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    (OUT / f"audit_{stamp}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / f"audit_{stamp}.md").write_text(render(res), encoding="utf-8")
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render(res))
    return 1 if res["critical"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
