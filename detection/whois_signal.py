#!/usr/bin/env python3
"""whois_signal.py — Señal organizativa de bajo coste para la atribución.

La atribución actual del radar es ESTRUCTURAL únicamente (coordinación,
anomalía, infraestructura compartida, densidad de red). NO incorpora evidencia
organizativa: quién está detrás del dominio, cuándo se registró, quién financia
las cuentas. Este módulo añade UNA señal de ese tipo, barata y sin API key:
RDAP (registro WHOIS moderno, HTTP público) sobre los dominios que los clusters
HIGH/CRITICAL comparten de forma dominante.

Qué detecta (evidencia débil, solo de apoyo):
  - Dominio registrado hace poco (<2 años) => posible infraestructura creada
    ad hoc para la campaña (señal a investigar, no prueba).
  - Re-registro / transferencia reciente de un dominio antiguo => posible
    cambio de manos (reutilización de dominios quemados).
  - Nube o servicio anonimizador de registro (privacy/proxy) => reduce la
    trazabilidad.

Qué NO hace: no resuelve quién está detrás, no es atribución de actor. Solo
alimenta la columna "evidence" / el análisis con un dato organizativo duro.

Uso (CLI):
  python detection/whois_signal.py                # audit de clusters HIGH/CRITICAL
  python detection/whois_signal.py --min-score 60 --top 3 --json
"""
import argparse
import json
import re
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path("/home/deploy/hybrid-fimi-radar")
DB = ROOT / "data" / "radar.db"
UA = {"User-Agent": "radar-fimi/0.1 (auditoria OSINT, contacto info-fimi@viajeinteligencia.com)"}
_ANOS_RECIENTE = 2     # dominio <2 años => señal
_ANOS_TRANSFER = 1     # transferencia en el último año => señal

_SERVICIOS_PRIVACIDAD = ("whoisguard", "withheld", "privacy", "proxy", "registrar-safe",
                         "knockknockwhois", "domainsbyproxy")


def _dominios_cluster(conn, cluster_id, top_n=5):
    """Dominios dominantes en los eventos miembros del cluster (con frecuencia)."""
    urls = conn.execute(
        "SELECT url FROM cluster_events WHERE cluster_id=? AND url!=''", (cluster_id,)).fetchall()
    doms = {}
    for (u,) in urls:
        m = re.search(r"https?://([^/]+)", str(u or ""))
        if m:
            d = m.group(1).lower()
            if d.startswith("www."):
                d = d[4:]
            doms[d] = doms.get(d, 0) + 1
    return sorted(doms.items(), key=lambda kv: -kv[1])[:top_n]


def rdap_domain(domain, timeout=12):
    """Consulta RDAP (registro moderno) de un dominio. Devuelve dict resumido."""
    try:
        req = urllib.request.Request(f"https://rdap.org/domain/{domain}", headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except Exception as e:
        return {"dominio": domain, "error": str(e)[:120]}
    events = {(e.get("eventAction") or ""): (e.get("eventDate") or "") for e in data.get("events", [])}
    reg = events.get("registration", "")
    exp = events.get("expiration", "")
    trf = events.get("transfer", "")
    # registrador / entidades
    entidades = data.get("entities", [])
    registrante = ""
    for ent in entidades:
        roles = ent.get("roles", [])
        if "registrant" in roles or "registrar" in roles:
            vcard = ent.get("vcardArray", [[], []])[1] if len(ent.get("vcardArray", [])) > 1 else []
            for item in vcard:
                if item and item[0] == "fn":
                    registrante = item[3]
                    break
        if registrante:
            break
    # ¿servicio de privacidad?
    blob = json.dumps(data).lower()
    privacidad = any(s in blob for s in _SERVICIOS_PRIVACIDAD)
    return {
        "dominio": domain,
        "registrado": reg[:10],
        "expira": exp[:10],
        "transferencia": trf[:10],
        "registrante": registrante[:80],
        "privacidad": bool(privacidad),
    }


def _sennas(info, hoy):
    """Convierte el dict RDAP en señales interpretables (evidencia débil)."""
    if "error" in info:
        return "consulta RDAP fallida"
    sennas = []
    try:
        yr = int(info.get("registrado", "0")[:4])
        if yr and hoy.year - yr < _ANOS_RECIENTE:
            sennas.append(f"dominio registrado hace <{_ANOS_RECIENTE} años ({yr})")
    except Exception:
        pass
    try:
        yt = int(info.get("transferencia", "0")[:4])
        if yt and hoy.year - yt <= _ANOS_TRANSFER:
            sennas.append(f"transferencia reciente ({yt})")
    except Exception:
        pass
    if info.get("privacidad"):
        sennas.append("registro con privacidad/proxy")
    if not sennas:
        sennas.append("dominio estable (sin señales organizativas)")
    return "; ".join(sennas)


def auditar(conn, min_score=60, top_domains=3):
    """Audita clusters con overall >= min_score: RDAP de sus dominios top."""
    hoy = __import__("datetime").date.today()
    rows = conn.execute(
        "SELECT id, cluster_label, tema_id, overall_score FROM clusters"
        " WHERE overall_score>=? ORDER BY overall_score DESC", (min_score,)).fetchall()
    resultado = []
    for r in rows:
        cid, label, tema, ov = r[0], r[1], r[2], r[3]
        doms = _dominios_cluster(conn, cid, top_domains)
        info_doms = []
        for d, n in doms:
            info = rdap_domain(d)
            info["frecuencia"] = n
            info["sennas"] = _sennas(info, hoy)
            info_doms.append(info)
        resultado.append({
            "cluster": label, "tema": tema, "overall": ov,
            "dominios": info_doms,
            "n_dominios_altos": sum(1 for x in info_doms if "registrado hace <" in x.get("sennas", "")),
        })
    return resultado


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--min-score", type=float, default=60.0)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    res = auditar(conn, min_score=args.min_score, top_domains=args.top)
    conn.close()

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    print(f"# Señal organizativa RDAP — clusters ≥ {args.min_score:.0f} · {len(res)} clusters")
    print("# Dominios compartidos por los clusters de alerta alta: registro, transferencia,")
    print("# privacidad. Evidencia DÉBIL de apoyo, no atribución de actor.\n")
    for c in res:
        print(f"## {c['cluster']} — {c['overall']:.1f}/100 ({c['tema']})")
        if not c["dominios"]:
            print("  (sin URLs en los eventos miembros)")
            continue
        for d in c["dominios"]:
            base = (f"  {d['dominio']:<42s} x{d['frecuencia']:<3d} reg={d.get('registrado') or '?'}"
                    f" trf={d.get('transferencia') or '-'}")
            print(base)
            print(f"     señales: {d.get('sennas')} · registrante: {d.get('registrante') or '?'}")
        if c["n_dominios_altos"]:
            print(f"  ⚠ {c['n_dominios_altos']} dominio(s) registrados hace <{_ANOS_RECIENTE} años "
                  f"-> posible infraestructura ad hoc (investigar)")


if __name__ == "__main__":
    main()
