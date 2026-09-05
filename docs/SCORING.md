# Scoring del radar FIMI: fórmula y ajuste por escala (05/Sep)

Documento de referencia del score 0-100 y de la corrección "por escala" aplicada
el 05/Sep (resultado del análisis externo contrastado con datos reales).
Complementa TRAZABILIDAD.md.

## Fórmula base (config.yaml -> scoring)

overall = sync*0.25 + content*0.20 + amp*0.20 + infra*0.15 + density*0.10 + anomaly*0.10

Componentes 0-100 por cluster:
- synchronization = coordination_score * 12  (cap 100)
- content_similarity = nº textos representativos * 25 (cap 100)
- amplification = señal global del run (igual para todo el tema)
- infrastructure = (urls+dominios compartidos) * 15 (cap 100)
- network_density = coordination_score * 6
- anomaly = anomaly_score * 100

Bandas: 0-19 NORMAL · 20-39 WATCH · 40-59 ANOMALOUS · 60-79 HIGH · 80-100 CRITICAL.

Los pesos son configurables por tema (temas.<tema>.scoring.weights): politica_nacional
(piloto) usa anomaly 0.40 / sync 0.15 / content 0.15 / amp·infra·density 0.10 para no
marcar como ANOMALOUS la coordinación partidista legítima.

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
