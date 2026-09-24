# Scoring del radar FIMI: fórmula y ajuste por escala (18/Sep)

Documento de referencia del score 0-100 y de la corrección "por escala" aplicada
el 05/Sep (resultado del análisis externo contrastado con datos reales).
Complementa TRAZABILIDAD.md.

## Fórmula base (config.yaml -> scoring)

overall = sync*0.1667 + content*0.1667 + amp*0.0556 + infra*0.1111 + anomaly*0.50

Componentes 0-100 por cluster:
- synchronization = coordination_score * 12  (cap 100)
- content_similarity = nº textos representativos * 25 (cap 100)
- amplification = señal global del run (igual para todo el tema)
- infrastructure = (urls+dominios compartidos) * 15 (cap 100)
- anomaly = anomaly_score * 100

**`network_density` ELIMINADO del compuesto (24/Sep, cambio "D").** Era
`coordination_score * 6`: una transformación lineal del MISMO `coordination_score`
que alimenta `synchronization` → doble conteo del eje de coordinación. Se quita y se
renormalizan los pesos restantes a suma 1. El componente se sigue calculando y
persistiendo (`network_density` en `clusters`) porque la hipótesis H3 de `attribution`
lo usa, pero ya NO pondera en `overall`.

Bandas: 0-19 NORMAL · 20-39 WATCH · 40-59 ANOMALOUS · 60-79 HIGH · 80-100 CRITICAL.

Los pesos son configurables por tema (temas.<tema>.scoring.weights): politica_nacional,
eeuu_politica y oriente_medio (piloto) usan anomaly 0.4444 y amplification 0.1111
(renormalizados tras quitar density) para no marcar como ANOMALOUS la coordinación
partidista/editorial legítima. La fase electoral (`fase_scoring`) usa anomaly 0.3261.

## Efecto medido del cambio D (24/Sep)

Dry-run en copia de la BD (3 temas) comparando producción vs D vs D+aminusamplification:
el impacto en bandas es **pequeño** (frontera_sur: HIGH 6→6 con D, 6→9 con D−amp;
oriente_medio: prácticamente igual; espana: sin cambio). Es decir, el doble conteo
**no inflaba materialmente** los HIGH: el cambio D es una mejora de **honestidad
metodológica**, no una corrección de alertas infladas. La amplificación global se
deja como está (quitarla subiría el peso de la anomalía y algunos HIGH).

## Escala (05/Sep): el orden invertido detectado

Diagnóstico con datos reales (vista activa, 44 clusters): un cluster de 2 cuentas
(frontera_sur_cluster_012, overall 79) puntuaba IGUAL o MÁS que uno de 49 cuentas
(frontera_sur_cluster_000, overall 78). El score premiaba la sincronización perfecta
de una pareja por encima de una red a gran escala: invertía la lógica de campaña.

### Antes (pre 05/Sep)
| Cluster | Cuentas | Overall | Banda |
|---|---|---|---|
| frontera_sur_cluster_012 | 2 | 79.0 | HIGH |
| frontera_sur_cluster_000 | 49 | 78.0 | HIGH |

### Después (05/Sep, scoring.scale_bonus + scoring.scale_floor + scale_cap)
| Cluster | Cuentas | Overall | Banda |
|---|---|---|---|
| frontera_sur_cluster_000 | 49 | 82.4 | CRITICAL |
| frontera_sur_cluster_010 | 2 (22 ev) | 79.0 | HIGH |

## Reglas nuevas (detection/scoring.py -> solve_scale)

Orden de aplicación: compute_scores -> scale_bonus -> scale_floor -> scale_cap.

1. scale_bonus: bonus = min(cap 3.5, cuentas * 0.08). A igualdad de componentes,
   más cuentas puntúan más. Corrige el orden invertido (49 cuentas > 2 cuentas).
2. scale_floor (PISO HÍBRIDO): cluster con <3 cuentas => banda máx WATCH y se marca
   "Posible ruido de bajo volumen", SALVO evidencia adicional:
   - >= except_events (10) eventos sostenidos, o
   - infraestructura compartida >= except_infra (80).
   Con excepción puede llegar a HIGH (79), pero NUNCA a CRITICAL.
3. scale_cap (ya existía): CRITICAL exige >=10 cuentas; HIGH exige >=2.

Efecto en la vista real (frontera_sur, 34 clusters tras el ciclo): 20 parejas de
2 cuentas y 2-3 eventos cayeron de bandas altas a WATCH 39 con marcador "ruido";
las parejas con volumen real (012=22 ev, 006=31 ev) conservaron HIGH; los clusters
grandes (000=49 cuentas, 001=15) pasaron a CRITICAL.

Config por tema: temas.<tema>.scoring.scale_floor / scale_bonus hacen merge sobre
los globales (misma mecánica que weights / scale_min_accounts).

## Por qué no es "ruido" todo lo de 2 cuentas
La pareja de activistas puede ser señal (crisis de Ceuta: 2 cuentas + 22-31 eventos
sostenidos en ventana corta = coordinación operativa real). El piso híbrido distingue
"2 cuentas efímeras" (2-3 eventos, probable ruido) de "2 cuentas con volumen" (señal):
el volumen/infraestructura actúa como evidencia adicional para no perder esos casos.
