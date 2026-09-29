# FIMI — qué mide realmente el grafo de coordinación (y qué no)

**Medición 29-Sep-2026**, sobre copia de `data/radar.db` (1052 clusters, 20.016 eventos
miembro). Guiones: `medir_aristas.py` (usa el `build_edges` de producción), `medir_nucleo.py`,
`medir_aliases.py`, `v1_triaje.py`, `efecto_combinado.py`, `medir_kcore_real.py` (server, `/tmp`).
Documento complementario de [`composicion-bandas-20260929.md`](composicion-bandas-20260929.md),
que mide las bandas; este mide **el grafo que las produce**.

> ⚠️ **Corrección 29-Sep (segunda versión de este doc).** La primera versión decía que «el 23 % de
> HIGH y el 96 % de WATCH no tienen ningún nodo de grado ≥3» y que el núcleo dejaría HIGH en ~34.
> **Era un proxy, no la métrica de producción, y sobrestimaba el problema ~2,5×.** La métrica real
> es el **k-core** (`graph_metrics.kcore_subset`, ya persistido en `assessments.kcore`): exige que
> las cuentas estén conectadas **mutuamente** (un ciclo), no que una cuenta tenga 3+ vecinos.
> Con la métrica correcta el efecto es **HIGH 100 → 87**, no 100 → 34. Lección: medir con el
> código de producción, nunca con una reimplementación laxa. La §3 está reescrita con los datos
> buenos; el resto de secciones se mantiene.

---

## 1. Resumen

El grafo de coordinación mide una sola cosa: **cuántas cuentas distintas republicaron la misma
URL o un texto casi idéntico, y en qué momento**. Eso es amplificación, y es medible. Lo que
no puede hacer —con los umbrales actuales— es distinguir **una campaña** de **una noticia que
acaba de breaking**. El único discriminador diseñado para eso (ráfaga de publicación,
`tight_timing`) **apenas se dispara**.

## 2. Las aristas que existen de verdad (código de producción reejecutado)

`build_edges()` ejecutado sobre 3 temas, con la distancia temporal mínima entre posts de las
dos cuentas de cada arista:

| Tema | aristas | `same_url` | `near_duplicate_text` | `tight_timing` (ráfaga) | Δt mediana near-dup |
|---|---|---|---|---|---|
| elecciones | 937 | 734 (94 % ≤24 h) | 257 (83 % ≤24 h) | **4** | 0,6 h |
| oriente_medio | 2.387 | 1.917 (91 %) | 559 (72 %) | **11** | 6,0 h |
| inteligencia_artificial | 1.363 | 876 (84 %) | 565 (72 %) | **0** | 3,3 h |

Dos cosas quedan claras:

1. **El grafo no es un «blob temático de meses».** Hipótesis que probé y **quedó falsada**: si
   el near-dup usara la media de todos los textos de la cuenta sin ventana, las aristas se
   separarían por días o semanas. No es así: la mediana de Δt es de 0,6-6 h y el 72-94 % de
   las aristas están dentro de 24 h. Las señales débiles (`same_hashtag`, `same_domain`,
   `same_action_pattern`) **solo refuerzan** aristas que ya son fuertes (`coordination.py:181`),
   así que no crean comunidades por hashtags.
2. **La señal de campaña está prácticamente apagada.** `bursty()` marca 104 de 33.904 cuentas
   (0,3 %) y solo 9 son «bursty» en las últimas 24 h. De ahí que `tight_timing` sea 4, 11 y 0
   aristas. El detector de ráfagas —lo único que distinguiría «campaña» de «noticia»— no
   aporta nada en producción.

## 3. La estructura interna: k-core (métrica de producción)

Dentro de cada cluster, aristas por cluster: **mediana 1**. La estructura mayoritaria es una
cadena, no un núcleo. Medido con `kcore_subset` (k-core máximo del subgrafo inducido: el
mayor conjunto en el que **todos** los nodos tienen grado ≥ k):

| Banda | `kcore >= 2` (núcleo mutuo) | `kcore == 1` (cadena pura) | ≥1 arista de peso ≥10 |
|---|---|---|---|
| HIGH | **86 / 100 (86 %)** | 14 | 28 % |
| ANOMALOUS | 169 / 363 (47 %) | 194 | 10 % |
| WATCH | 45 / 576 (8 %) | 531 | 2 % |

**El k-core discrimina de forma monótona** (8 % → 47 % → 86 %): no es un recorte arbitrario,
es una propiedad que acompaña a la banda alta. Y el problema real es el inverso al que
sospechaba: **solo 14 de 100 HIGH eran cadenas puras**, no 23. El 86 % de HIGH sí tiene un
núcleo de cuentas conectadas mutuamente, con nucleos de hasta 17 cuentas
(`eeuu_politica_cluster_001`: k=9, núcleo 17, 52 cuentas).

Lo que **sí** es cierto, y sigue siendo el punto débil: la mediana de **1 arista por cluster**.
Un cluster con 52 cuentas y un núcleo de 17 no es «52 cuentas coordinando»: son unas pocas
cuentas enlazadas y el resto colgando. Por eso el k-core es **necesario pero no suficiente**,
y por eso el triage de los 63 supervivientes del gate B (§4) sale 71 % con Jaccard de texto
<0,15 y 61/63 con ventana >72 h: **sostained amplification**, no ráfaga.

**Ejemplo de lo que el núcleo NO arregla**: `oriente_medio_cluster_000` tiene 83 cuentas,
1.890 h de ventana, Jaccard medio 0,04 entre cuentas… **y 49 nodos de grado ≥3**. Sobrevive
al gate y sigue siendo, en el fondo, un eco largo. Por eso el gate de núcleo es el primer
paso, no el último.

## 4. Gate B (cuenta dominante) y su combinación con el núcleo

Sobre los 3 temas con aristas recalculadas (74 HIGH), aplicando reglas sucesivas:

| Regla | HIGH restantes |
|---|---|
| actual antes del 29-Sep | 74 |
| – cuenta dominante ≥55 % (`dac`) | 53 |
| – sindicación de prensa (`syndicated_wire` supported) | **45** |
| – (adicional) sin k-core ≥2 | 74 → **64** (no acumulable con las anteriores: ver nota) |

**Nota sobre la última fila**: el gate de núcleo y el gate B actúan sobre conjuntos que se
solapan parcialmente. Medido por separado sobre los 100 HIGH de los 8 temas: el núcleo
retira 13, el gate B retira 37. Sumados, sobre los 74 HIGH de los 3 temas, la combinación
núcleo + B + sindicación da **~45-48** (no se volvió a medir el cruce exacto de las tres
reglas a la vez: es una simulación, no una decisión).

Los 45 del gate B + sindicación: 18 `sustained_amplification`, 12 `unresolved`,
8 `single_source_feed`, 3 `automated_non_malicious`, 3 `synchronized_without_operator`,
**1 `cross_account_synchrony`**. Mediana de 8 cuentas. 12 de ellos tienen una arista de peso ≥10.

## 5. Hipótesis que probé y **quedaron falsadas** (no las toques)

- **«Los clusters son el tema entero».** Falso: el mayor cluster es 11-37 % de los eventos de
  su tema, no el 100 %. El clustering sí discrimina.
- **«Las aristas unen cuentas de meses distintos por temática».** Falso (§2.1).
- **«Cuentas duplicadas por el mismo actor (bridges, mirrors) inflan el recuento».** Parcialmente
  cierto y **menor de lo que esperaba**: 52 grupos de handles equivalentes
  (`x.bsky.social` = `x.wsocial.eu` = `x.berlin.social.ap.bridged`), 6,9 % de clusters
  afectados y solo **2 HIGH** que declaran 3+ cuentas y son en realidad 2 actores. No justifica
  un gate por sí solo, pero conviene contar actores, no handles.
- **«Casi todos los HIGH son cadenas sin núcleo».** **Falso con la métrica correcta** (§3):
  son 14 de 100, no 23 de 74. El proxy de grado ≥3 lo hace parecer peor de lo que es.

## 6. Lo que el producto puede decir y lo que no

**Sí, con evidencia:** «N cuentas republicaron la misma pieza en la misma ventana horaria».
Eso es lo que el sistema mide, y es un hecho verificable y útil. Desde el 29-Sep, además de una
condición estructural: **la banda alta exige que esas cuentas formen un núcleo de conexión
mutua** (k-core ≥2), no solo una cadena.

**No:** «detectar FIMI» o «coordinación». Con 1 `cross_account_synchrony` en 1052 clusters,
0 CRITICAL y `tight_timing` inerte, la afirmación correcta es **«observamos amplificación
simultánea»**, y la diferencia entre noticia y campaña **no está implementada**.

## 7. Los discriminadores: estado tras el 29-Sep

1. ✅ **APLICADO — exigir núcleo para banda alta.** `band_gate.min_kcore: 2` (HIGH y CRITICAL)
   en `config.yaml` + `band_gate(..., kcore=…)` en `scoring.py` (default 2, por la lección del
   24/Sep: el default del código decide). Una arista = amplificación; sin ciclo = máx
   ANOMALOUS. **HIGH 100 → 87** en los 8 temas. Tests: `test_band_gate_exige_nucleo_mutuo_para_HIGH`.
2. **PENDIENTE — reactivar la ráfaga con ventana real**: `bursty()` debe evaluarse en una
   ventana (p. ej. últimas 6-24 h), no como propiedad permanente del histórico de la cuenta.
   Es el discriminador que falta entre «noticia» y «campaña».
3. **PENDIENTE — contar actores, no handles**: normalizar bridges/mirrors antes del recuento de
   cuentas y del test de dominancia. Solo 2 HIGH afectados.
4. **PENDIENTE — gate B** (ninguna cuenta domina + sin sindicación): HIGH → 63. Depende de 3
   para que «cuentas» signifique «actores».

Cada uno cambia la definición de lo que el observatorio afirma. **El 2 y el 3 son decisión del
dueño**; el 4 se puede medir en cualquier momento y no aplicado (100 → 63).
