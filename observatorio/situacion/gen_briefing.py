#!/usr/bin/env python3
"""Briefing de cambios de la ficha de situación. Compara snapshots fechados, sin IA."""
import argparse
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
DEFAULT_SIT = HERE / "situacion_frontera_sur.json"
DEFAULT_SNAPSHOTS = HERE / "snapshots"
DEFAULT_OUT = HERE.parent / "ceuta/situacion/cambios/index.html"
MADRID = ZoneInfo("Europe/Madrid")


def e(value):
    return html.escape(str(value or ""))


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def text_key(value):
    return " ".join(str(value).split()).strip()


def short_hash(value):
    return hashlib.sha256(text_key(value).encode("utf-8")).hexdigest()[:12]


def build_snapshot(sit, date):
    episodes = {ep: sit["episode_status"][ep] for ep in sit["episode_order"]}
    contradictions = {}
    for item in sit["contradicciones"]:
        contradictions[item["id"]] = {"hash": short_hash(item["texto"]), "text": item["texto"]}
    return {
        "date": date,
        "situacion_version": sit["version"],
        "episodes": episodes,
        "sources": {d: v["role"] for d, v in sit["source_roles"].items()},
        "open_questions": sorted(text_key(x) for x in sit["open_questions"]),
        "contradictions": contradictions,
    }


def previous_snapshot(snapshots, current):
    candidates = []
    for path in snapshots.glob("*.json"):
        try:
            data = load(path)
            if data.get("date", "") < current:
                candidates.append(data)
        except Exception:
            continue
    return max(candidates, key=lambda x: x["date"]) if candidates else None


def diff(prev, cur):
    out = {"episodes_added": [], "episodes_removed": [], "status_changed": [],
           "sources_added": [], "sources_removed": [], "role_changed": [],
           "questions_added": [], "questions_removed": [],
           "contradictions_added": [], "contradictions_removed": [], "contradictions_changed": []}
    if not prev:
        return out
    pe, ce = prev.get("episodes", {}), cur.get("episodes", {})
    out["episodes_added"] = sorted(set(ce) - set(pe))
    out["episodes_removed"] = sorted(set(pe) - set(ce))
    out["status_changed"] = [
        {"id": k, "before": pe[k], "after": ce[k]}
        for k in sorted(set(pe) & set(ce)) if pe[k] != ce[k]
    ]
    ps, cs = prev.get("sources", {}), cur.get("sources", {})
    out["sources_added"] = sorted(set(cs) - set(ps))
    out["sources_removed"] = sorted(set(ps) - set(cs))
    out["role_changed"] = [
        {"domain": k, "before": ps[k], "after": cs[k]}
        for k in sorted(set(ps) & set(cs)) if ps[k] != cs[k]
    ]
    pq, cq = set(prev.get("open_questions", [])), set(cur.get("open_questions", []))
    out["questions_added"] = sorted(cq - pq)
    out["questions_removed"] = sorted(pq - cq)
    pc, cc = prev.get("contradictions", {}), cur.get("contradictions", {})
    out["contradictions_added"] = sorted(set(cc) - set(pc))
    out["contradictions_removed"] = sorted(set(pc) - set(cc))
    out["contradictions_changed"] = sorted(
        k for k in set(pc) & set(cc) if pc[k].get("hash") != cc[k].get("hash")
    )
    return out


def count_changes(d):
    return sum(len(v) for v in d.values())


def status_label(sit, status):
    return sit["status_labels"].get(status, status)


def render(sit, cur, prev, d, out):
    changes = count_changes(d)
    if prev is None:
        headline = "Primera edición: se guarda el corte de hoy para comparar la próxima semana."
    elif changes:
        headline = f"{changes} cambio(s) respecto al corte del {prev['date']}."
    else:
        headline = f"Sin cambios respecto al corte del {prev['date']}."
    status_rows = "".join(
        f'<tr><td>{e(ep)}</td><td>{e(status_label(sit, prev["episodes"].get(ep, "—")) if prev else "—")}</td>'
        f'<td><b>{e(status_label(sit, cur["episodes"][ep]))}</b></td></tr>'
        for ep in sit["episode_order"]
    )
    def list_items(values, empty):
        return "".join(f"<li>{e(x)}</li>" for x in values) or f'<li class="muted">{e(empty)}</li>'
    def status_changes():
        return "".join(
            f'<li><b>{e(x["id"])}</b>: {e(status_label(sit, x["before"]))} → <b>{e(status_label(sit, x["after"]))}</b></li>'
            for x in d["status_changed"]
        ) or '<li class="muted">Sin cambios de estado.</li>'
    def role_changes():
        return "".join(
            f'<li><b>{e(x["domain"])}</b>: {e(x["before"])} → <b>{e(x["after"])}</b></li>'
            for x in d["role_changed"]
        ) or '<li class="muted">Sin cambios de papel documental.</li>'
    doc = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cambios · Frontera Sur — Observatorio de lo publicado</title>
<meta name="description" content="Briefing determinista de cambios de la ficha de situación de Frontera Sur: estados, fuentes, preguntas y contradicciones.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/observatorio/ceuta/situacion/cambios/">
<meta property="og:type" content="article"><meta property="og:title" content="Cambios · Frontera Sur">
<meta property="og:description" content="Qué ha cambiado en la ficha de situación, sin IA y sin atribuciones.">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/observatorio/ceuta/situacion/cambios/">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/observatorio/og-frontera-sur.png">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="https://fimi.viajeinteligencia.com/observatorio/og-frontera-sur.png">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Article","headline":"Cambios · Frontera Sur","dateModified":"{e(cur["date"])}","isPartOf":{{"@type":"WebSite","name":"Observatorio de lo publicado"}}}}</script>
<style>
:root{{--a:#b45309;--i:#1e293b;--m:#64748b;--l:#fde68a}}*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:linear-gradient(180deg,#fff,#fffaf5);color:var(--i);line-height:1.6}}a{{color:var(--a)}}.wrap{{max-width:980px;margin:0 auto;padding:28px 18px 60px}}h1{{font-size:1.8rem;line-height:1.2;margin:0 0 6px}}h2{{font-size:1.15rem;border-bottom:2px solid var(--l);padding-bottom:5px;margin:28px 0 10px}}.lead{{font-size:1rem;color:#334155;max-width:72ch}}.muted{{color:var(--m);font-size:.84rem}}.sitehead{{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;border-bottom:1px solid #e2e8f0;padding-bottom:12px;margin-bottom:18px}}.brand{{font-weight:800;text-decoration:none;font-size:1.05rem}}.sitehead nav{{display:flex;gap:6px;flex-wrap:wrap;font-size:.82rem}}.sitehead nav a{{text-decoration:none;padding:4px 7px;border-radius:6px}}.sitehead nav a:hover{{background:#fff7ed}}.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:16px 0}}.kpi{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px;text-align:center}}.kpi b{{display:block;font-size:1.5rem;color:var(--a);line-height:1.1}}.kpi span{{font-size:.76rem;color:var(--m)}}.box{{background:#fff7ed;border-left:4px solid var(--a);padding:10px 14px;border-radius:7px;margin:12px 0}}.box.neutral{{background:#f8fafc;border-left-color:#64748b}}table{{width:100%;border-collapse:collapse;font-size:.88rem}}th,td{{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}}th{{background:#f8fafc;font-size:.78rem;text-transform:uppercase;color:#475569}}ul{{padding-left:20px}}li{{margin:5px 0}}.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.two .box{{margin:0}}.foot{{display:grid;grid-template-columns:1.4fr 1fr 1.2fr;gap:20px;margin-top:40px;border-top:2px solid var(--l);padding-top:22px;color:#334155;font-size:.86rem}}.foot b{{display:block;color:var(--i);margin-bottom:6px}}.foot a{{display:block;text-decoration:none;margin:4px 0}}.foot p{{margin:0 0 8px;color:var(--m)}}@media(max-width:720px){{.kpis,.two,.foot{{grid-template-columns:1fr}}h1{{font-size:1.45rem}}}}
</style></head><body><div class="wrap">
<div class="sitehead"><a class="brand" href="/observatorio/">Observatorio de lo publicado</a><nav><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/">Frontera Sur</a><a href="/observatorio/ceuta/situacion/">Situación</a><a href="/observatorio/metodo/">Método</a><a href="/observatorio/fuentes/">Fuentes</a></nav></div>
<p class="muted">Briefing de cambios · Frontera Sur</p><h1>Qué ha cambiado</h1><p class="lead">Comparación determinista entre el corte actual y el anterior. No usa IA, no añade hechos y no atribuye intenciones.</p><p class="muted">Corte actual: <b>{e(cur["date"])}</b> · Corte anterior: <b>{e(prev["date"]) if prev else "sin corte anterior"}</b></p>
<div class="kpis"><div class="kpi"><b>{len(sit["episode_order"])}</b><span>fichas</span></div><div class="kpi"><b>{changes}</b><span>cambios detectados</span></div><div class="kpi"><b>0</b><span>fuentes primarias</span></div></div>
<div class="box"><b>Resumen.</b> {e(headline)}</div>
<h2>1. Estado de las fichas</h2><table><thead><tr><th>Ficha</th><th>Anterior</th><th>Actual</th></tr></thead><tbody>{status_rows}</tbody></table>
<div class="box neutral"><b>Cambios de estado.</b><ul>{status_changes()}</ul></div>
<h2>2. Fuentes y papel documental</h2><div class="two"><div class="box neutral"><b>Añadidas</b><ul>{list_items(d["sources_added"], "Ninguna.")}</ul></div><div class="box neutral"><b>Retiradas</b><ul>{list_items(d["sources_removed"], "Ninguna.")}</ul></div></div><div class="box neutral"><b>Cambios de papel.</b><ul>{role_changes()}</ul></div>
<h2>3. Preguntas abiertas</h2><div class="two"><div class="box neutral"><b>Añadidas</b><ul>{list_items(d["questions_added"], "Ninguna.")}</ul></div><div class="box neutral"><b>Retiradas</b><ul>{list_items(d["questions_removed"], "Ninguna.")}</ul></div></div>
<h2>4. Contradicciones</h2><div class="two"><div class="box neutral"><b>Añadidas</b><ul>{list_items(d["contradictions_added"], "Ninguna.")}</ul></div><div class="box neutral"><b>Retiradas / modificadas</b><ul>{list_items(d["contradictions_removed"] + d["contradictions_changed"], "Ninguna.")}</ul></div></div>
<h2>5. Límites de esta comparación</h2><ul><li>Compara la <b>ficha curada</b>, no la captura automática ni el volumen de titulares.</li><li>Un cambio de estado no es una prueba nueva: puede ser una corrección editorial.</li><li>La ausencia de cambios no significa que no haya publicaciones nuevas; el registro diario está en <a href="/observatorio/ceuta/">Frontera Sur</a>.</li><li>No se reintroducen clústeres, bandas, puntuaciones ni atribuciones.</li></ul>
<div class="box"><b>Qué no es.</b> No es un boletín de noticias ni una validación de los hechos. Es un registro de qué ha cambiado en la ficha y qué sigue pendiente.</div>
<p><a href="/observatorio/ceuta/situacion/"><b>← Volver a la ficha de situación</b></a> · <a href="/observatorio/ceuta/">Registro de Frontera Sur</a></p>
<footer class="foot"><div><b>Observatorio de lo publicado</b><p>Briefing de cambios sobre la ficha curada. Sin IA y sin atribuciones.</p><p>Generado: {e(cur["date"])}.</p></div><div><b>Secciones</b><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/">Frontera Sur</a><a href="/observatorio/ceuta/situacion/">Situación</a><a href="/observatorio/metodo/">Método</a></div><div><b>Contacto</b><a href="mailto:info-fimi@viajeinteligencia.com">info-fimi@viajeinteligencia.com</a><a href="/observatorio/privacidad/">Privacidad</a></div></footer>
</div></body></html>'''
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--situacion", type=Path, default=DEFAULT_SIT)
    ap.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--date", default=datetime.now(MADRID).date().isoformat())
    args = ap.parse_args()
    sit = load(args.situacion)
    cur = build_snapshot(sit, args.date)
    prev = previous_snapshot(args.snapshots, args.date)
    d = diff(prev, cur)
    args.snapshots.mkdir(parents=True, exist_ok=True)
    (args.snapshots / f"{args.date}.json").write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render(sit, cur, prev, d, args.out)
    print(f"{args.out} · {count_changes(d)} cambio(s) · anterior {prev['date'] if prev else '—'}")


if __name__ == "__main__":
    main()
