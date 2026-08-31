"""European Hybrid & FIMI Radar — dashboard Streamlit.

Lee de data/radar.db (generado por detection/run_fimi.py).
Secciones: Situación · Clusters · Atribución · Hipótesis · Narrativas · Red · Evidencia.
Sin auth, sin API, sin servicios externos.
"""
import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
DB = ROOT / "data" / "radar.db"

st.set_page_config(page_title="European Hybrid & FIMI Radar", layout="wide", page_icon="📡")

TAB_SIT, TAB_CLUST, TAB_ATR, TAB_HIP, TAB_NARR, TAB_RED, TAB_EVID = st.tabs(
    ["Situación", "Clusters", "Atribución", "Hipótesis", "Narrativas", "Red", "Evidencia"])


@st.cache_data(ttl=30)
def load():
    if not DB.exists():
        return None
    con = sqlite3.connect(DB)
    clusters = pd.read_sql("SELECT * FROM clusters ORDER BY overall_score DESC", con)
    assessments = pd.read_sql("SELECT * FROM assessments ORDER BY overall_score DESC", con)
    indicators = pd.read_sql("SELECT * FROM indicators", con)
    events = pd.read_sql("SELECT * FROM events LIMIT 500", con)
    narratives = pd.read_sql("SELECT * FROM narratives", con)
    con.close()
    return {"clusters": clusters, "assessments": assessments,
            "indicators": indicators, "events": events, "narratives": narratives}


data = load()

if data is None:
    st.warning("Sin datos. Ejecuta: python detection/run_fimi.py --input data/raw/events.csv --db data/radar.db")
    st.stop()

# ============ SITUACIÓN ============
with TAB_SIT:
    st.header("Situación actual")
    c = data["clusters"]
    if c.empty:
        st.info("No hay clusters activos. La ausencia de señal es un resultado válido.")
    else:
        n_crit = len(c[c["overall_score"] >= 80])
        n_high = len(c[(c["overall_score"] >= 60) & (c["overall_score"] < 80)])
        n_anom = len(c[(c["overall_score"] >= 40) & (c["overall_score"] < 60)])
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Clusters", len(c))
        k2.metric("CRITICAL (80+)", n_crit)
        k3.metric("HIGH (60-79)", n_high)
        k4.metric("ANOMALOUS (40-59)", n_anom)
        st.markdown("#### Clusters activos por score")
        for _, r in c.iterrows():
            band = "CRITICAL" if r["overall_score"] >= 80 else ("HIGH" if r["overall_score"] >= 60 else "ANOMALOUS")
            col = "#dc2626" if band == "CRITICAL" else ("#f97316" if band == "HIGH" else "#eab308")
            st.markdown(f"**{r['cluster_label']}** — {r['overall_score']:.0f}/100 ({band}) "
                        f"· atribución: {r['confidence']}")
            st.progress(min(1.0, r["overall_score"] / 100))

# ============ CLUSTERS ============
with TAB_CLUST:
    st.header("Clusters y componentes")
    if data["clusters"].empty:
        st.info("Sin clusters.")
    else:
        a = data["assessments"]
        if not a.empty:
            view = a[["cluster_id", "coordination_score", "amplification_score", "anomaly_score",
                      "infrastructure_score", "network_density", "overall_score", "confidence", "assessment"]]
            st.dataframe(view, hide_index=True, width="stretch")
        st.caption("Coordination, Amplification, Anomaly, Infrastructure, Network density — componentes del score, sin redondear.")

# ============ ATRIBUCIÓN ============
with TAB_ATR:
    st.header("Atribución (agnóstica al actor)")
    a = data["assessments"]
    if a.empty:
        st.info("Sin atribuciones.")
    else:
        for _, r in a.iterrows():
            st.markdown(f"**Cluster {r['cluster_id']}** — atribución: `{r['attribution']}` · "
                        f"confianza `{r['attribution_confidence']}`")
            st.markdown(f"- **Evidencia:** {r['attribution_evidence']}")
            st.markdown(f"- **Evidencia faltante:** {r['missing_evidence']}")
            st.markdown("---")
    st.caption("La atribución es un módulo SEPARADO del detector. La ausencia de atribución es un resultado válido.")

# ============ HIPÓTESIS ============
with TAB_HIP:
    st.header("Hipótesis alternativas (anti sesgo de confirmación)")
    a = data["assessments"]
    if a.empty:
        st.info("Sin hipótesis.")
    else:
        for _, r in a.iterrows():
            st.markdown(f"**Cluster {r['cluster_id']}**")
            try:
                hyp = json.loads(r["hypotheses_json"])
                for h in hyp[:5]:
                    st.markdown(f"- `{h['hypothesis']}` {h['label']}: score {h['score']}")
            except Exception:
                st.write(r["hypotheses_json"])
            st.markdown("---")

# ============ NARRATIVAS ============
with TAB_NARR:
    st.header("Narrativas emergentes")
    if data["narratives"].empty:
        st.info("Sin narrativas registradas todavía (se poblarán con datos reales).")
    else:
        st.dataframe(data["narratives"], hide_index=True, width="stretch")

# ============ RED ============
with TAB_RED:
    st.header("Red de coordinación")
    st.caption("Grafo: cuentas conectadas por evidencia de coordinación. "
               "Disponible cuando se analizan datos con coordinación real.")
    st.info("El grafo se renderiza desde edges.csv cuando existe (datos con aristas).")

# ============ EVIDENCIA ============
with TAB_EVID:
    st.header("Evidencia (auditable)")
    if data["events"].empty:
        st.info("Sin eventos en BD.")
    else:
        ev = data["events"]
        if "text" in ev.columns:
            st.dataframe(ev[["timestamp", "source", "title", "text", "url"]].head(100),
                         hide_index=True, width="stretch")
        else:
            st.dataframe(ev.head(100), hide_index=True, width="stretch")
    st.caption("Cada evento se guarda con raw_json (observación original) — auditabilidad.")

st.markdown("---")
st.caption("European Hybrid & FIMI Radar — los scores indican posible actividad coordinada, "
           "nunca atribución por defecto. La ausencia de atribución es un resultado analítico válido.")
