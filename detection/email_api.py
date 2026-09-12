#!/usr/bin/env python3
"""email_api.py — Backend del newsletter por email del radar FIMI.

Servidor HTTP (solo stdlib, sin dependencias, mismo patrón que newsletter_api.py)
que escucha en 127.0.0.1:3311 y se expone por nginx como https://fimi.viajeinteligencia.com/api/*.

Endpoints:
  GET  /api/health            -> {"ok": true}
  POST /api/subscribe         -> body JSON {"email": "...", "temas": ["frontera_sur", ...]}
                                  Guarda canal='email' (confirmado=0), envía doble opt-in.
  GET  /api/confirmar?id=...  -> marca confirmado=1 (enlace del email). Redirige a la landing.
  GET  /api/baja?id=...       -> elimina la suscripción de email. Redirige a la landing.
  POST /api/feedback          -> body JSON {"tema": "...", "voto": "si|no|ns"}
                                  Voto ligero "¿Te resulta útil este tema?". Rate-limit por IP.
  POST /api/sugerir           -> body JSON {"texto": "..."}
                                  Sugerencia de tema nuevo (web). Rate-limit por IP + reenvío
                                  al dueño por Telegram (chan FIMI_OWNER_CHAT).
  GET  /api/admin/feedback    -> resumen de votos y sugerencias. Header `x-admin-secret`
                                  (env/.env FIMI_ADMIN_SECRET). SOLO visible para el dueño:
                                  sin cómputo público (un radar FIMI no debe ser manipulable).

  --- API pública v1 (read-only, S4; datos ya públicos, CORS *) ---
  GET  /api/v1                -> índice de endpoints + meta/aviso
  GET  /api/v1/temas          -> resumen por tema (n_clusters, n_alerta, top)
  GET  /api/v1/tema/<slug>    -> clusters del tema (componentes, confianza, atribución)
  GET  /api/v1/cluster/<label>-> cluster completo + evidencia (eventos)
  GET  /api/v1/openapi.json   -> especificación OpenAPI 3.0
  GET  /api/v1/health         -> estado del servicio

Envía con Resend (API key de /home/deploy/newsletter/.env, emisor newsletter@viajeinteligencia.com).
La tabla suscripciones la crea schema_suscripciones.py en data/radar.db; feedback/sugerencias
las crea schema_feedback.py.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
ENV_NEWSLETTER = Path("/home/deploy/newsletter/.env")
ENV_RADAR = ROOT / ".env"
PORT = 3311
BASE_URL = "https://fimi.viajeinteligencia.com"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LIMIT_PER_IP = 10          # subscribe: 10/h
LIMIT_FEEDBACK_IP = 20     # feedback/sugerir combinados: 20/h
TEMAS_VALIDOS = {"frontera_sur", "geopolitica_ue_marruecos", "politica_nacional",
                 "eeuu_politica", "oriente_medio"}
VOTOS_VALIDOS = {"si", "no", "ns"}
_hits = {}
_hits_fb = {}

import sqlite3
from schema_suscripciones import init as _init_schema
from schema_feedback import init as _init_feedback


def load_env(filepath: Path):
    cfg = {}
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return cfg


def resend_cfg():
    cfg = load_env(ENV_NEWSLETTER) or load_env(ENV_RADAR)
    return cfg.get("RESEND_API_KEY", ""), cfg.get("RESEND_FROM", "")


def short_id(canal: str, destino: str) -> str:
    return hashlib.sha256(f"{canal}:{destino}".encode()).hexdigest()[:24]


def send_email(to, subject, html):
    """Envía un email vía Resend (urllib, User-Agent como el newsletter)."""
    key, frm = resend_cfg()
    if not key or not frm:
        return False
    ua = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120"}
    payload = json.dumps({"from": frm, "to": [to], "subject": subject, "html": html}).encode()
    h = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    h.update(ua)
    req = urllib.request.Request("https://api.resend.com/emails", data=payload, headers=h, method="POST")
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception:
        return False


def rate_ok(ip: str) -> bool:
    now = time.time()
    _hits[ip] = [t for t in _hits.get(ip, []) if now - t < 3600]
    if len(_hits[ip]) >= LIMIT_PER_IP:
        return False
    _hits[ip].append(now)
    return True


def rate_feedback_ok(ip: str) -> bool:
    """Rate-limit combinado para feedback (votos) + sugerencias: 20/h por IP."""
    now = time.time()
    _hits_fb[ip] = [t for t in _hits_fb.get(ip, []) if now - t < 3600]
    if len(_hits_fb[ip]) >= LIMIT_FEEDBACK_IP:
        return False
    _hits_fb[ip].append(now)
    return True


def admin_secret() -> str:
    # Fuente de verdad: .env en disco (evita desfase con environ de pm2 tras restart sin --update-env)
    cfg = load_env(ENV_RADAR) or {}
    file_secret = (cfg.get("FIMI_ADMIN_SECRET", "") or "").strip().strip('"').strip("'")
    # si el .env trae la línea completa por error, extrae tras =
    if "=" in file_secret and len(file_secret) > 30:
        file_secret = file_secret.split("=", 1)[1].strip().strip('"').strip("'")
    env_secret = (os.environ.get("FIMI_ADMIN_SECRET", "") or "").strip().strip('"').strip("'")
    if "=" in env_secret and len(env_secret) > 30:
        env_secret = env_secret.split("=", 1)[1].strip().strip('"').strip("'")
    return file_secret or env_secret

def _clean_admin_header(v: str) -> str:
    # tolera que el usuario pegue "FIMI_ADMIN_SECRET=valor" o con comillas/espacios
    v = (v or "").strip().replace("\u200b","").replace("\u200d","").replace("\ufeff","").strip()
    v = v.strip('"').strip("'").strip()
    if "=" in v:
        # si pegó la línea completa del .env, quédate con el valor
        v = v.split("=", 1)[1].strip().strip('"').strip("'").strip()
    return v


def _leer_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def temas_estado():
    """Estado de cada tema + señales de promoción/cierre (solo lectura).

    El sistema NO decide: solo expone si un tema ya cumplió la ventana de
    promoción (data/promocion_<tema>.json → ready) o si check_cierre lo marcó
    como candidato (data/cierre_<tema>.json → candidato). La acción la toma el
    dueño desde el panel admin.
    """
    import yaml
    try:
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        cfg = {}
    temas_cfg = cfg.get("temas", {}) or {}
    out = []
    for t, meta in temas_cfg.items():
        meta = meta or {}
        prom = _leer_json(ROOT / "data" / f"promocion_{t}.json")
        cierre = _leer_json(ROOT / "data" / f"cierre_{t}.json")
        out.append({
            "tema": t,
            "nombre": meta.get("nombre", t),
            "estado": meta.get("estado", "produccion"),
            "ready": bool(prom.get("ready")),
            "promocion_inicio": prom.get("inicio"),
            "candidato_cierre": bool(cierre.get("candidato")),
            "cierre_motivos": cierre.get("motivos") or [],
        })
    return out


def _temas_cli(args, timeout=90):
    """Ejecuta temas_cli.py (edita config + bitácora) SIN regenerar el dashboard."""
    cmd = [sys.executable, str(ROOT / "detection" / "temas_cli.py")] + list(args) + ["--no-regen"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def _regen_bg():
    """Lanza gen_fimi_html.py en segundo plano si no hay ya uno corriendo."""
    try:
        r = subprocess.run(["pgrep", "-f", "detection/gen_fimi_html.py"], capture_output=True)
        if r.returncode == 0:
            return False
    except Exception:
        pass
    try:
        subprocess.Popen(
            [sys.executable, str(ROOT / "detection" / "gen_fimi_html.py")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, cwd=str(ROOT))
        return True
    except Exception:
        return False


def _replay_meta():
    """Metadata de reproducibilidad del score para el export (S2).

    Con esto, cualquiera puede recomputar la banda/overall del cluster con la
    MISMA configuración que el radar usó en ese ciclo (weights, bands, escala,
    ventana de coordinación, versión del código). Viene de config.yaml y git;
    si algo falla, devuelve parcial (nunca rompe el export).
    """
    cfg = {}
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    scoring = (cfg or {}).get("scoring", {}) or {}
    coord = (cfg or {}).get("coordination", {}) or {}
    capture = (cfg or {}).get("capture", {}) or {}
    ver = ""
    try:
        _r = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=10)
        ver = (_r.stdout or "").strip() or "sin-tag"
    except Exception:
        ver = "desconocida"
    return {
        "programa": "hybrid-fimi-radar",
        "version": ver,
        "window_days": coord.get("window_days", 90),
        "capture_window_days": capture.get("window_days", 90),
        "scoring": {
            "weights": (scoring.get("weights") or {}),
            "bands": (scoring.get("bands") or {}),
            "scale_min_accounts": (scoring.get("scale_min_accounts") or {}),
            "scale_floor": (scoring.get("scale_floor") or {}),
            "scale_bonus": (scoring.get("scale_bonus") or {}),
            "origen_unico": (scoring.get("origen_unico") or {}),
        },
    }


def _band_of(score, bands):
    """Asigna banda según el dict de bandas de config.yaml (NORMAL/WATCH/...)."""
    if not isinstance(bands, dict) or not bands:
        return "NORMAL"
    for _b, _rango in bands.items():
        if len(_rango) == 2 and _rango[0] <= score <= _rango[1]:
            return _b
    return "NORMAL"


def exportar_cluster(cluster_label: str, fmt: str = "csv"):
    """Exporta la evidencia (cluster_events) de un cluster de la vista activa.

    cluster_label es el label p.ej. 'frontera_sur_cluster_000'. El export se
    limita a clusters de la vista ACTIVA (el snapshot más reciente en
    clusters), no a la BD histórica, y devuelve los eventos miembros con su
    fuente/autor/titular/URL para auditoría OSINT o compartir.

    Desde S2 incluye un bloque "replay" (JSON) con la configuración y versión
    exactas que produjeron el score (reproducibilidad). En CSV los campos de
    replay se añaden como columnas por fila para no romper la estructura
    tabular de eventos.

    Devuelve (content_type, bytes, filename) o levanta KeyError si no existe.
    """
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT c.id, c.cluster_label, c.tema_id, c.overall_score, c.created_at"
            " FROM clusters c WHERE c.cluster_label=? LIMIT 1",
            (cluster_label,)).fetchone()
        if not row:
            raise KeyError("cluster no encontrado en la vista activa")
        asm = conn.execute(
            "SELECT * FROM assessments WHERE cluster_id=? LIMIT 1", (row["id"],)).fetchone()
        evs = conn.execute(
            "SELECT ts, source, author, title, text, url FROM cluster_events"
            " WHERE cluster_id=? ORDER BY ts", (row["id"],)).fetchall()
    finally:
        conn.close()

    cid = cluster_label
    fecha_snap = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(row["created_at"]))
    lat = [dict(r) for r in evs]
    replay = _replay_meta()
    banda = _band_of(row["overall_score"] or 0, replay["scoring"]["bands"])
    if fmt == "json":
        payload = {
            "cluster_label": cid,
            "tema": row["tema_id"],
            "overall_score": row["overall_score"],
            "banda": banda,
            "snapshot_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(row["created_at"])),
            "snapshot_iso": fecha_snap,
            "n_eventos": len(lat),
            "fuentes": sorted({e["source"] for e in lat}),
            "autores": sorted({e["author"] for e in lat if e.get("author")}),
            "replay": replay,
        }
        if asm:
            payload["components"] = {
                k: asm[k] for k in (
                    "coordination_score", "amplification_score", "anomaly_score",
                    "infrastructure_score", "network_density", "confidence",
                    "assessment", "missing_evidence")
                if k in asm.keys()}
            payload["attribution"] = {
                k: asm[k] for k in (
                    "attribution", "attribution_confidence", "attribution_evidence")
                if k in asm.keys()}
            try:
                payload["hypotheses"] = json.loads(asm["hypotheses_json"]) if asm["hypotheses_json"] else []
            except Exception:
                payload["hypotheses"] = []
        payload["eventos"] = lat
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        return ("application/json", body, f"fimi-evidence-{cid}.json")
    # CSV
    import io
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    # cabecera con los campos de replay una vez (no tabular, no rompe la fila
    # de datos: se pone como primera fila prefijada con '#' -> columna clave)
    w.writerow(["# replay", "programa", replay["programa"]])
    w.writerow(["# replay", "version", replay["version"]])
    w.writerow(["# replay", "window_days", replay["window_days"]])
    w.writerow(["# replay", "capture_window_days", replay["capture_window_days"]])
    w.writerow(["# replay", "banda", banda])
    w.writerow(["cluster_label", "tema", "overall_score", "banda", "ts_utc",
                "source", "author", "title", "text", "url"])
    for e in evs:
        w.writerow([cid, row["tema_id"], row["overall_score"], banda,
                    time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(e["ts"])),
                    e["source"], e["author"], e["title"], e["text"], e["url"]])
    body = buf.getvalue().encode("utf-8")
    return ("text/csv; charset=utf-8", body, f"fimi-evidence-{cid}.csv")


# ---------------------------------------------------------------------------
# API pública v1 (read-only, S4). Expone la MISMA señal que el dashboard, con
# framing autodescriptivo para que sea interpretable sin contexto previo:
# banda, componentes 0-100, confianza, atribución, disclaimers y replay.
# Los cluster_label NO son estables entre ciclos (se regeneran cada 6h) -> cada
# respuesta es una FOTO del último ciclo (meta.snapshot=true) y lleva el aviso.
# No expone endpoints admin ni datos personales.
# ---------------------------------------------------------------------------
API_SCHEMA = "v1"

_DISCLAIMER_CLUSTER = ("Señal de comportamiento observable (coordinación/amplificación). "
                       "No constituye atribución de FIMI ni identifica actores.")
_DISCLAIMER_API = ("Datos públicos de un radar de coordinación. Señal, no atribución. "
                   "Los identificadores de cluster no son estables entre ciclos: cada "
                   "respuesta es una foto del último ciclo (meta.snapshot=true).")


def _temas_catalogo():
    """Temas en produccion/piloto desde config.yaml (slug, nombre, estado)."""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        cfg = {}
    out = []
    for slug, meta in (cfg.get("temas") or {}).items():
        meta = meta or {}
        estado = meta.get("estado", "produccion")
        if estado in ("produccion", "piloto"):
            out.append({"tema": slug, "nombre": meta.get("nombre", slug), "estado": estado})
    return out


def _api_meta():
    """Bloque meta autodescriptivo común a todas las respuestas v1."""
    r = _replay_meta()
    return {
        "programa": r["programa"],
        "version": r["version"],
        "schema": API_SCHEMA,
        "generado_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "snapshot": True,
        "aviso": _DISCLAIMER_API,
        "replay": r,
    }


def _cluster_obj(row, bands):
    """Convierte una fila (join cluster+assessment) en el objeto JSON v1."""
    d = dict(row)
    comps = {k: d.get(k) for k in (
        "coordination_score", "amplification_score", "anomaly_score",
        "infrastructure_score", "network_density")}
    try:
        hyp = json.loads(d.get("hypotheses_json") or "[]")
    except Exception:
        hyp = []
    label = d.get("cluster_label")
    return {
        "cluster_label": label,
        "overall_score": d.get("overall_score"),
        "banda": _band_of(d.get("overall_score") or 0, bands),
        "components": comps,
        "confidence": d.get("confidence"),
        "assessment": d.get("assessment"),
        "missing_evidence": d.get("missing_evidence"),
        "attribution": {
            "attribution": d.get("attribution") or "UNKNOWN",
            "attribution_confidence": d.get("attribution_confidence"),
            "attribution_evidence": d.get("attribution_evidence"),
        },
        "hypotheses": hyp,
        "disclaimer": _DISCLAIMER_CLUSTER,
        "export": f"/api/export?cluster={label}&fmt=json",
    }


def _api_temas():
    """Resumen por tema del snapshot actual: n_clusters, n_alerta y top."""
    bands = _replay_meta()["scoring"]["bands"]
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        temas = []
        for t in _temas_catalogo():
            rows = conn.execute(
                "SELECT c.cluster_label, c.overall_score, c.created_at "
                "FROM clusters c WHERE c.tema_id=? ORDER BY c.overall_score DESC",
                (t["tema"],)).fetchall()
            n = len(rows)
            alerta = sum(1 for r in rows if (r["overall_score"] or 0) >= 60)
            top = None
            snap = None
            if rows:
                top = {
                    "cluster_label": rows[0]["cluster_label"],
                    "overall_score": rows[0]["overall_score"],
                    "banda": _band_of(rows[0]["overall_score"] or 0, bands),
                }
                snap = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(rows[0]["created_at"]))
            temas.append({
                "tema": t["tema"], "nombre": t["nombre"], "estado": t["estado"],
                "n_clusters": n, "n_alerta": alerta, "top": top, "snapshot_utc": snap,
            })
        return {"meta": _api_meta(), "temas": temas}
    finally:
        conn.close()


def _api_tema(slug):
    """Clusters de un tema (snapshot actual) con componentes y atribución."""
    replay = _replay_meta()
    bands = replay["scoring"]["bands"]
    cat = {t["tema"]: t for t in _temas_catalogo()}
    if slug not in cat:
        return None
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT c.cluster_label, c.overall_score, c.created_at, c.confidence, "
            " a.coordination_score, a.amplification_score, a.anomaly_score, "
            " a.infrastructure_score, a.network_density, a.assessment, a.missing_evidence, "
            " a.attribution, a.attribution_confidence, a.attribution_evidence, a.hypotheses_json "
            "FROM clusters c LEFT JOIN assessments a ON a.cluster_id = c.id "
            "WHERE c.tema_id=? ORDER BY c.overall_score DESC", (slug,)).fetchall()
    finally:
        conn.close()
    clusters = [_cluster_obj(r, bands) for r in rows]
    snap = None
    if rows:
        snap = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(rows[0]["created_at"]))
    return {
        "meta": _api_meta(),
        "tema": slug,
        "nombre": cat[slug]["nombre"],
        "estado": cat[slug]["estado"],
        "snapshot_utc": snap,
        "n_clusters": len(clusters),
        "clusters": clusters,
    }


def _openapi_spec():
    """Especificación OpenAPI 3.0.3 de la API pública v1."""
    v = _replay_meta()["version"]
    comp = {
        "type": "object",
        "properties": {
            "coordination_score": {"type": "number", "description": "Coordinación 0-100"},
            "amplification_score": {"type": "number", "description": "Amplificación 0-100 (global del tema)"},
            "anomaly_score": {"type": "number", "description": "Anomalía 0-100"},
            "infrastructure_score": {"type": "number", "description": "Infraestructura compartida 0-100"},
            "network_density": {"type": "number", "description": "Densidad de red 0-100"},
        },
    }
    cluster = {
        "type": "object",
        "properties": {
            "cluster_label": {"type": "string", "description": "ID del cluster en ESTE ciclo (no estable entre ciclos)"},
            "overall_score": {"type": "number"},
            "banda": {"type": "string", "enum": ["NORMAL", "WATCH", "ANOMALOUS", "HIGH", "CRITICAL"]},
            "components": comp,
            "confidence": {"type": "string"},
            "assessment": {"type": "string"},
            "missing_evidence": {"type": "string"},
            "attribution": {
                "type": "object",
                "properties": {
                    "attribution": {"type": "string"},
                    "attribution_confidence": {"type": "string"},
                    "attribution_evidence": {"type": "string"},
                },
            },
            "hypotheses": {"type": "array", "items": {"type": "object"}},
            "disclaimer": {"type": "string"},
            "export": {"type": "string"},
        },
    }
    meta = {
        "type": "object",
        "properties": {
            "programa": {"type": "string"},
            "version": {"type": "string"},
            "schema": {"type": "string"},
            "generado_utc": {"type": "string"},
            "snapshot": {"type": "boolean"},
            "aviso": {"type": "string"},
        },
    }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Radar FIMI — API pública",
            "version": f"{API_SCHEMA} ({v})",
            "description": _DISCLAIMER_API,
            "contact": {"url": "https://fimi.viajeinteligencia.com/"},
            "license": {"name": "Open Source",
                        "url": "https://github.com/mcasrom/hybrid-fimi-radar"},
        },
        "servers": [{"url": "https://fimi.viajeinteligencia.com"}],
        "paths": {
            "/api/v1/temas": {"get": {"summary": "Resumen de temas monitorizados",
                "responses": {"200": {"description": "OK", "content": {"application/json": {"schema": {
                    "type": "object", "properties": {"meta": meta, "temas": {"type": "array"}}}}}}}}},
            "/api/v1/tema/{slug}": {"get": {"summary": "Clusters de un tema (snapshot actual)",
                "parameters": [{"name": "slug", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "OK", "content": {"application/json": {"schema": {
                    "type": "object", "properties": {"meta": meta, "clusters": {"type": "array", "items": cluster}}}}}},
                    "404": {"description": "Tema no monitorizado"}}}},
            "/api/v1/cluster/{label}": {"get": {"summary": "Cluster completo con evidencia (eventos)",
                "parameters": [{"name": "label", "in": "path", "required": True, "schema": {"type": "string"},
                                "example": "frontera_sur_cluster_000"}],
                "responses": {"200": {"description": "OK"}, "404": {"description": "Cluster no encontrado"}}}},
            "/api/v1/health": {"get": {"summary": "Estado del servicio",
                "responses": {"200": {"description": "OK"}}}},
        },
    }


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj, ctype="application/json"):
        if isinstance(obj, str):
            body = obj.encode()
        else:
            body = json.dumps(obj).encode()
        self.send_response(code)
        # CORS para semilla newsletter (blog -> fimi)
        if self.path.startswith("/api/subscribe"):
            self._cors()
        # API pública v1: lectura abierta (datos públicos) -> CORS *
        if self.path.startswith("/api/v1"):
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_download(self, code, body: bytes, ctype, filename):
        """Envía un fichero como descarga (Content-Disposition attachment)."""
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        origin = self.headers.get("Origin", "")
        allowed = {"https://analisis.pruebapublica.com", "https://www.pruebapublica.com", "https://pruebapublica.com", "https://fimi.viajeinteligencia.com", "https://www.viajeinteligencia.com", "https://viajeinteligencia.com"}
        if origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Credentials", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-admin-secret")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _ip(self):
        return self.client_address[0]

    # ---------- rutas ----------
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        if path == "/api/health":
            return self._send(200, {"ok": True})
        if path == "/api/confirmar":
            sid = (q.get("id") or [""])[0]
            if not sid:
                return self._send(400, {"error": "falta id"})
            conn = _init_schema()
            conn.execute("UPDATE suscripciones SET confirmado=1 WHERE id=? AND canal='email'", (sid,))
            conn.commit()
            conn.close()
            return self._redirect(BASE_URL + "?confirmado=1")
        if path == "/api/baja":
            sid = (q.get("id") or [""])[0]
            if sid:
                conn = _init_schema()
                conn.execute("DELETE FROM suscripciones WHERE id=? AND canal='email'", (sid,))
                conn.commit()
                conn.close()
            return self._redirect(BASE_URL + "?baja=1")
        if path == "/api/admin/feedback":
            # Solo el dueno: header x-admin-secret == FIMI_ADMIN_SECRET (env/.env).
            if _clean_admin_header(self.headers.get("x-admin-secret", "")) != admin_secret():
                return self._send(403, {"error": "prohibido"})
            conn = _init_feedback()
            votos = {}
            for row in conn.execute("SELECT tema, voto, COUNT(*) n FROM feedback GROUP BY tema, voto"):
                votos.setdefault(row["tema"], {})[row["voto"]] = row["n"]
            sugs = [dict(r) for r in conn.execute(
                "SELECT id, texto, canal, created_at AS fecha_alta FROM sugerencias ORDER BY id DESC LIMIT 50")]
            conn.close()
            return self._send(200, {"ok": True, "votos": votos, "sugerencias": sugs})
        if path == "/api/admin/suscriptores":
            if _clean_admin_header(self.headers.get("x-admin-secret", "")) != admin_secret():
                return self._send(403, {"error": "prohibido"})
            proyecto = (q.get("proyecto") or [""])[0].strip().lower()[:20]
            conn = _init_schema()
            if proyecto in ("fimi", "blog", "pruebapublica", "viajeinteligencia", "loteria"):
                rows = conn.execute(
                    "SELECT id, destino, proyecto, temas, frecuencia, confirmado, fecha_alta "
                    "FROM suscripciones WHERE canal='email' AND proyecto=? ORDER BY fecha_alta DESC", (proyecto,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, destino, proyecto, temas, frecuencia, confirmado, fecha_alta "
                    "FROM suscripciones WHERE canal='email' ORDER BY fecha_alta DESC").fetchall()
            data = [dict(r) for r in rows]
            # conteo por proyecto para el selector
            conteo = {}
            for r in conn.execute("SELECT proyecto, COUNT(*) n FROM suscripciones WHERE canal='email' GROUP BY proyecto"):
                conteo[r["proyecto"] or "fimi"] = r["n"]
            conn.close()
            return self._send(200, {"ok": True, "suscriptores": data, "conteo": conteo, "proyecto": proyecto or "todos"})
        if path == "/api/admin/temas":
            # Estado de temas + señales de promoción/cierre. Solo el dueño.
            if _clean_admin_header(self.headers.get("x-admin-secret", "")) != admin_secret():
                return self._send(403, {"error": "prohibido"})
            return self._send(200, {"ok": True, "temas": temas_estado()})
        if path == "/api/export":
            # Evidencia por cluster (OSINT): devuelve cluster_events de un
            # cluster de la vista activa en CSV/JSON. Datos ya públicos en las
            # tarjetas; el export facilita auditoría/compartir.
            cid = (q.get("cluster") or [""])[0]
            fmt = (q.get("fmt") or ["csv"])[0]
            if fmt not in ("csv", "json"):
                return self._send(400, {"error": "fmt invalido (csv|json)"})
            if not cid:
                return self._send(400, {"error": "falta cluster"})
            if not re.match(r"^[a-z0-9_]+(_cluster_[0-9]{3})?$", cid):
                return self._send(400, {"error": "cluster_label invalido"})
            try:
                ctype, body, fname = exportar_cluster(cid, fmt)
            except KeyError:
                return self._send(404, {"error": f"cluster no encontrado: {cid}"})
            return self._send_download(200, body, ctype, fname)
        # ---- API pública v1 (read-only) ----
        if path in ("/api/v1", "/api/v1/"):
            return self._send(200, {
                "meta": _api_meta(),
                "endpoints": [
                    {"path": "/api/v1/temas", "desc": "Resumen de temas monitorizados (snapshot actual)"},
                    {"path": "/api/v1/tema/<slug>", "desc": "Clusters de un tema con componentes, confianza y atribución"},
                    {"path": "/api/v1/cluster/<label>", "desc": "Cluster completo + evidencia (eventos)"},
                    {"path": "/api/v1/openapi.json", "desc": "Especificación OpenAPI 3.0"},
                    {"path": "/api/v1/health", "desc": "Estado del servicio"},
                ],
            })
        if path == "/api/v1/health":
            return self._send(200, {"ok": True, "schema": API_SCHEMA,
                                    "version": _replay_meta()["version"]})
        if path == "/api/v1/temas":
            return self._send(200, _api_temas())
        if path == "/api/v1/openapi.json":
            return self._send(200, _openapi_spec())
        if path.startswith("/api/v1/tema/"):
            slug = path[len("/api/v1/tema/"):].strip("/")
            if not re.match(r"^[a-z0-9_]+$", slug):
                return self._send(400, {"error": "tema invalido"})
            d = _api_tema(slug)
            if d is None:
                return self._send(404, {"error": f"tema no monitorizado: {slug}"})
            return self._send(200, d)
        if path.startswith("/api/v1/cluster/"):
            cid = path[len("/api/v1/cluster/"):].strip("/")
            if not re.match(r"^[a-z0-9_]+(_cluster_[0-9]{3})?$", cid):
                return self._send(400, {"error": "cluster_label invalido"})
            try:
                ctype, body, _fn = exportar_cluster(cid, "json")
            except KeyError:
                return self._send(404, {"error": f"cluster no encontrado: {cid}"})
            payload = json.loads(body.decode("utf-8"))
            payload["meta"] = _api_meta()
            payload["disclaimer"] = _DISCLAIMER_CLUSTER
            return self._send(200, payload)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        admin_paths = ("/api/admin/tema-estado", "/api/admin/tema-cerrar")
        if parsed.path not in ("/api/subscribe", "/api/feedback", "/api/sugerir") + admin_paths:
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return self._send(400, {"error": "sin cuerpo"})
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            return self._send(400, {"error": "json invalido"})
        if parsed.path in admin_paths:
            # Acciones de estado de temas: SOLO el dueño (x-admin-secret). El
            # sistema no decide; aquí solo se ejecuta lo que el dueño pulsa.
            if _clean_admin_header(self.headers.get("x-admin-secret", "")) != admin_secret():
                return self._send(403, {"error": "prohibido"})
            tema = str(data.get("tema") or "").strip()
            nota = str(data.get("nota") or "").strip()[:300]
            if tema not in {t["tema"] for t in temas_estado()}:
                return self._send(400, {"error": "tema invalido"})
            if parsed.path == "/api/admin/tema-cerrar":
                rc, out = _temas_cli(["cerrar", tema, "--nota", nota or "cierre desde panel admin"])
            else:
                estado = str(data.get("estado") or "").strip()
                if estado not in ("produccion", "piloto"):
                    return self._send(400, {"error": "estado invalido (produccion|piloto)"})
                rc, out = _temas_cli(["estado", tema, estado,
                                      "--nota", nota or f"cambio a {estado} desde panel admin"])
            lanzado = _regen_bg()
            return self._send(200 if rc == 0 else 500,
                              {"ok": rc == 0, "salida": out, "regen": lanzado})
        if parsed.path == "/api/feedback":
            if not rate_feedback_ok(self._ip()):
                return self._send(429, {"error": "demasiadas peticiones"})
            tema = str(data.get("tema") or "").strip()
            voto = str(data.get("voto") or "").strip().lower()
            if tema not in {t["tema"] for t in temas_estado()}:
                return self._send(400, {"error": "tema invalido"})
            if voto not in VOTOS_VALIDOS:
                return self._send(400, {"error": "voto invalido (si|no|ns)"})
            conn = _init_feedback()
            conn.execute("INSERT INTO feedback (tema, voto, ip) VALUES (?,?,?)",
                         (tema, voto, self._ip()))
            conn.commit()
            conn.close()
            return self._send(200, {"ok": True})
        if parsed.path == "/api/sugerir":
            if not rate_feedback_ok(self._ip()):
                return self._send(429, {"error": "demasiadas peticiones"})
            texto = (data.get("texto") or "").strip()
            if not texto:
                return self._send(400, {"error": "escribe una sugerencia"})
            if len(texto) > 500:
                texto = texto[:500]
            conn = _init_feedback()
            conn.execute("INSERT INTO sugerencias (texto, canal, ip) VALUES (?,?,?)",
                         (texto, "web", self._ip()))
            conn.commit()
            conn.close()
            self._avisar_dueno(texto, "web")
            return self._send(200, {"ok": True})
        email = (data.get("email") or "").strip().lower()
        if not rate_ok(self._ip()):
            return self._send(429, {"error": "demasiadas peticiones"})
        temas = data.get("temas") or []
        proyecto = (data.get("proyecto") or "fimi").strip().lower()[:20]
        if proyecto not in ("fimi", "blog", "pruebapublica", "viajeinteligencia", "loteria"):
            proyecto = "fimi"
        if not EMAIL_RE.match(email):
            return self._send(400, {"error": "email invalido"})
        if proyecto == "blog" and not temas:
            temas = ["blog"]
        if not isinstance(temas, list) or not temas:
            return self._send(400, {"error": "selecciona al menos un tema"})
        temas = [str(t) for t in temas[:6]]
        sid = short_id("email", email)
        conn = _init_schema()
        row = conn.execute("SELECT * FROM suscripciones WHERE id=?", (sid,)).fetchone()
        if row:
            conn.execute("UPDATE suscripciones SET temas=?, proyecto=?, confirmado=0 WHERE id=?",
                         (json.dumps(temas), proyecto, sid))
            conn.commit()
            conn.close()
            self._reenviar_confirmacion(email, sid, temas)
            return self._send(200, {"ok": True, "confirmado": False})
        conn.execute(
            "INSERT INTO suscripciones (id, canal, destino, temas, frecuencia, confirmado, proyecto)"
            " VALUES (?,?,?,?,?,?,?)",
            (sid, "email", email, json.dumps(temas), "semanal", 0, proyecto))
        conn.commit()
        conn.close()
        self._reenviar_confirmacion(email, sid, temas)
        return self._send(200, {"ok": True, "confirmado": False})

    def _reenviar_confirmacion(self, email, sid, temas):
        # Narrativa por proyecto: si temas==["blog"] es suscripción al blog, no al radar
        es_blog = len(temas)==1 and temas[0]=="blog"
        link = f"{BASE_URL}/api/confirmar?id={sid}"
        if es_blog:
            html = ('<div style="font-family:system-ui;max-width:600px;margin:0 auto">'
                    '<h2>Análisis · Confirma tu suscripción</h2>'
                    '<p>Gracias por suscribirte al <b>blog Análisis</b> (analisis.pruebapublica.com).</p>'
                    '<p>Recibirás un <b>resumen semanal</b> con los últimos artículos — sin spam, sin cesión a terceros. Puedes darte de baja en cualquier correo (enlace “Darme de baja”).</p>'
                    f'<p><a href="{link}" style="background:#c2410c;color:#fff;padding:10px 18px;'
                    'border-radius:6px;text-decoration:none;font-weight:700">Confirmar suscripción</a></p>'
                    '<p style="font-size:.82rem;color:#64748b">Si no fuiste tú, ignora este correo.</p>'
                    '<p style="font-size:.8rem;color:#888">Análisis · analisis.pruebapublica.com · vía FIMI semilla única</p></div>')
            subj = "Análisis · Confirma tu suscripción"
        else:
            html = ('<div style="font-family:system-ui;max-width:600px;margin:0 auto">'
                    '<h2>Radar FIMI · Confirma tu suscripción</h2>'
                    f'<p>Te suscribiste al resumen semanal de: <b>{", ".join(temas)}</b>.</p>'
                    '<p>Para activar el envío, confirma tu email:</p>'
                    f'<p><a href="{link}" style="background:#c2410c;color:#fff;padding:10px 18px;'
                    'border-radius:6px;text-decoration:none;font-weight:700">Confirmar suscripción</a></p>'
                    '<p>Si no fuiste tú, ignora este correo.</p>'
                    '<p style="font-size:.8rem;color:#888">Radar FIMI · fimi.viajeinteligencia.com · 1 email/semana, baja en 1 clic</p></div>')
            subj = "Radar FIMI · Confirma tu suscripción"
        send_email(email, subj, html)

    def _avisar_dueno(self, texto, canal="web"):
        """Reenvía una sugerencia de tema al dueño (Telegram + email info-fimi)."""
        token = os.environ.get("FIMI_TELEGRAM_BOT_TOKEN", "") or (load_env(ENV_RADAR) or {}).get("FIMI_TELEGRAM_BOT_TOKEN", "")
        if ":" in token:
            chat = os.environ.get("FIMI_OWNER_CHAT", "") or (load_env(ENV_RADAR) or {}).get("FIMI_OWNER_CHAT", "47652516")
            msg = ("📥 <b>Sugerencia de tema</b> para el radar FIMI\n"
                   f"Canal: {canal}\n\n{texto}")
            data = {
                "chat_id": str(chat),
                "text": msg,
                "parse_mode": "HTML",
            }
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=urllib.parse.urlencode(data).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"},
            )
            try:
                urllib.request.urlopen(req, timeout=15)
            except Exception as e:
                print(f"[telegram sugerencia] error: {e}")
        import html as _h
        send_email(
            "info-fimi@viajeinteligencia.com",
            "[Radar FIMI] Sugerencia de tema · " + texto[:60],
            f'<h3>📥 Nueva sugerencia de tema</h3>'
            f'<p><b>Canal:</b> {_h.escape(canal)}</p>'
            f'<p><b>Sugerencia:</b> {_h.escape(texto)}</p>'
            f'<p style="color:#888;font-size:.85rem">Radar FIMI · fimi.viajeinteligencia.com</p>',
        )


def main():
    _init_schema()
    _init_feedback()
    srv = HTTPServer(("127.0.0.1", PORT), H)
    print(f"[email_api] escuchando en 127.0.0.1:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
