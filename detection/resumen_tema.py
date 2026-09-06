#!/usr/bin/env python3
"""resumen_tema.py — Síntesis de 4-6 líneas por tema para el dashboard.

Composición de datos QUE YA EXISTEN y se calculan en el pipeline (score de
salud, clusters activos con componentes, narrativas sostenidas, narrativas
alineadas cross-topic y bitácora). Sin IA generativa ni nuevo cálculo de
señal: solo reglas condicionales simples sobre estructuras observables.

PRINCIPIO del proyecto (agnóstico al actor): las frases describen estructura
(coordinación, infraestructura, volumen, señal, madurez), NUNCA atribución a
actores ni interpretación política. Mismo tono que "Interpreta con cautela"
y "Sin evidencia concluyente".
"""
import re

# --- Reglas de veredicto según salud (0-100) y nº de narrativas sostenidas ---
def _veredicto(salud_score, n_sost):
    if salud_score is None:
        return "sin señal todavía (en recopilación)"
    if salud_score >= 70 and n_sost >= 5:
        return "tema plenamente vivo, señal sostenida"
    if salud_score >= 70:
        return "tema vivo con señal clara"
    if salud_score >= 40:
        return "funciona con reservas, volumen o señal moderados"
    return "señal débil, candidato a revisión (ver Bitácora)"


# --- Interpretación de componentes del cluster de mayor alerta ---
def _interpreta_cluster(cc):
    """Devuelve (frase_componentes, n_cuentas) para el cluster dado.

    Reglas sobre los 4 componentes (0-100), cubriendo las combinaciones más
    frecuentes. `cc` trae coordination_score, anomaly_score,
    infrastructure_score, network_density y el nº de cuentas en 'cuentas'.
    """
    coord = cc.get("coordination_score") or 0
    anom = cc.get("anomaly_score") or 0
    infra = cc.get("infrastructure_score") or 0
    dens = cc.get("network_density") or 0
    cuentas = cc.get("cuentas") or 0

    alta = 60
    if coord >= alta and infra >= alta and dens >= alta:
        return ("patrón compatible con red coordinada con infraestructura "
                "compartida", cuentas)
    if coord >= alta and infra < alta and dens < alta:
        return ("cuentas distintas repitiendo contenido, sin infraestructura "
                "técnica común evidente", cuentas)
    if infra >= alta and dens >= alta and coord < alta:
        if cuentas >= 5:
            return ("red amplia con infraestructura compartida (densidad alta) "
                    "pero sin sincronía temporal marcada entre las cuentas", cuentas)
        return ("infraestructura y densidad altas en un volumen pequeño de "
                "cuentas — señal débil de red, no concluyente", cuentas)
    if anom >= alta and coord >= alta:
        return ("anomalía alta sobre coordinación: comportamiento que se "
                "desvía de lo habitual para este tipo de cuentas", cuentas)
    if anom >= alta:
        return ("anomalía alta: comportamiento atípico respecto a la "
                "actividad normal", cuentas)
    if coord >= alta:
        return ("coordinación alta: cuentas actuando de forma sincronizada "
                "más allá del interés orgánico", cuentas)
    if coord < alta and anom < alta and infra < alta:
        return ("señales dentro de lo esperable; sin patrón inorgánico claro", cuentas)
    return ("combinación de señales de coordinación y anomalía; leer como "
            "hipótesis, no como veredicto", cuentas)


def _fmt_dias_operacion(dias):
    if dias is None:
        return "recién activado"
    if dias < 1:
        return "menos de 1 día operando"
    return f"{dias:.0f} días operando"


def generar_resumen_tema(tema_id, nombre, salud, cluster_top, sostenidas_tema,
                         grupos_na, bitacora_filas):
    """Devuelve una lista de strings (una por línea/párrafo) que sintetiza el
    estado del tema. Todos los argumentos ya vienen calculados por el caller.

    - salud: dict de salud_tema.salud_por_tema()[tema] o None
    - cluster_top: cluster (con columnas componentes) de mayor overall_score, o None
    - sostenidas_tema: lista de detectar_sostenidas(..., tema=tema_id)
    - grupos_na: narrativas alineadas (transversal) donde el tema pueda aparecer
    - bitacora_filas: filas de bitácora del tema ordenadas por fecha ASC (lista)
    """
    lineas = []
    s_score = (salud or {}).get("score")
    s_nivel = (salud or {}).get("nivel")
    dias = (salud or {}).get("dias_operacion")
    n_sost = len(sostenidas_tema) if sostenidas_tema else 0

    # 1) apertura: nombre + salud + veredicto
    salud_txt = f"{s_score:.0f}/100 · {s_nivel}" if s_score is not None else "sin score"
    lineas.append(
        f"**{nombre}** · salud {salud_txt} · {_fmt_dias_operacion(dias)} — "
        f"{_veredicto(s_score, n_sost)}.")

    # 2) cluster de mayor alerta
    if cluster_top is not None:
        score = cluster_top.get("overall_score") or 0
        banda = cluster_top.get("banda", "")
        frases_comp, cuentas = _interpreta_cluster(cluster_top)
        lineas.append(
            f"Cluster de mayor alerta: {score:.0f}/100 {banda} con {cuentas} "
            f"cuentas — {frases_comp}.")

    # 3) narrativas sostenidas del tema
    if n_sost:
        top2 = sorted(sostenidas_tema, key=lambda x: -(x.get("dias") or 0))[:2]
        detalle = "; ".join(
            f"\"{s.get('titulo', '')[:60]}\" ({s.get('dias')} días)"
            for s in top2)
        rest = f" y {n_sost - len(top2)} más" if n_sost > len(top2) else ""
        lineas.append(
            f"{n_sost} narrativa{'s' if n_sost != 1 else ''} sostenida"
            f"{'s' if n_sost != 1 else ''} (≥3 días): {detalle}{rest}.")
    else:
        lineas.append("Sin narrativas sostenidas (≥3 días) en la ventana actual.")

    # 4) narrativas alineadas cross-topic (solo si el tema aparece en algún grupo)
    if grupos_na:
        mios = [g for g in grupos_na if tema_id in (g.get("temas") or [])]
        if mios:
            # elegir el grupo más relevante para ESTE tema: el de mayor score
            # donde este tema no sea el único (cross-topic de verdad)
            g = max(mios, key=lambda x: (x.get("score_max") or 0, x.get("n_clusters") or 0))
            otros = [t for t in (g.get("temas") or []) if t != tema_id]
            if otros:
                lineas.append(
                    f"Comparte narrativa con otro tema del catálogo: {', '.join(otros)} "
                    f"({g.get('n_clusters') or 0} clusters y {g.get('n_cuentas') or 0} "
                    f"cuentas en el grupo; lee el detalle en 'Narrativas alineadas').")

    # 5) cierre: último cambio de estado/nota en bitácora (se ignoran los
    # `inicio` de ingesta — no son un "cambio"; si no hay más, se dice que
    # no hay cambios registrados desde el inicio).
    cambios = [x for x in (bitacora_filas or [])
               if x.get("tipo") not in ("inicio",)]
    if cambios:
        u = cambios[-1]  # el caller las pasa ordenadas por fecha asc
        f_ts = u.get("fecha")
        from datetime import datetime
        f_str = datetime.fromtimestamp(f_ts).strftime("%d/%m/%Y") if f_ts else ""
        accion = {"cambio_estado": "cambio de estado",
                  "cierre": "cierre",
                  "nota": "nota",
                  "sugerencia": "sugerencia del sistema"}.get(u.get("tipo"), u.get("tipo", ""))
        motivo = u.get("motivo", "")
        lineas.append(f"Último cambio en Bitácora ({f_str}): {accion}"
                      + (f" — {motivo}" if motivo else "") + ".")
    else:
        lineas.append("Sin cambios de estado registrados desde el inicio de ingesta.")

    return lineas
