# FIMI — qué mide realmente el grafo de coordinación (y qué no)

**Medición 29-Sep-2026**, sobre copia de `data/radar.db` (1052 clusters, 20.016 eventos
miembro). Guiones: `medir_aristas.py` (usa el `build_edges` de producción), `medir_nucleo.py`,
`medir_aliases.py`, `v1_triaje.py`, `efecto_combinado.py` (server, `/tmp`).
Documento complementario de [`composicion-bandas-20260929.md`](composicion-bandas-20260929.md),
que mide las bandas; este mide **el grafo que las produce**.

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
2. **La señal de campaña está praticamente apagada.** `bursty()` marca 104 de 33.904 cuentas
   (0,3 %) y solo 9 son «bursty» en las últimas 24 h. De ahí que `tight_timing` sea 4, 11 y 0
   aristas. El detector de ráfagas —lo único que distinguiría «campaña» de «noticia»— no
   aporta nada en producción.

## 3. El defecto preciso: una cadena puede llegar a HIGH

Dentro de cada cluster, aristas por cluster: **mediana 1**. La estructura real es una cadena
de enlaces débiles, no un núcleo. Reparto de clusters **sin ningún nodo de grado ≥ 3**
(o sea, sin ninguna cuenta conectada con dos o más cuentas del cluster):

| Banda | sin núcleo (grado ≥3) | con ≥1 arista de peso ≥10 |
|---|---|---|
| HIGH | **17 / 74 (23 %)** | 21 / 74 (28 %) |
| ANOMALOUS | 133 / 197 (67 %) | 19 / 197 (10 %) |
| WATCH | 309 / 322 (96 %) | 6 / 322 (2 %) |

Es decir: **el 96 % de WATCH es «dos cuentas compartieron un enlace»**, y **el 23 % de HIGH es
igualmente una cadena sin núcleo**. El sistema llama «coordinación» a un camino de enlaces,
que es lo que produce la percolación: una cuenta copia un post, esa cuenta comparte otro con
otra, y a las tres semanas hay un cluster de 83 cuentas que no se parecen en nada entre sí
(`oriente_medio_cluster_000`: 83 cuentas, 1.890 h de ventana, Jaccard medio de textos entre
cuentas 0,04).

**Lo que sí tiene estructura**: 21 de los 74 HIGH tienen al menos una arista de peso ≥10
(múltiples señales a la vez: misma URL + texto casi idéntico + ráfaga + dominio). Esos son
los únicos donde «coordinación» es una lectura defendible, y son 28 % de HIGH.

## 4. Gate B (cuenta dominante) y su combinación con el núcleo

Sobre los 3 temas con aristas recalculadas (74 HIGH), aplicando reglas sucesivas:

| Regla | HIGH restantes |
|---|---|
| actual | 74 |
| – cuenta dominante ≥55 % (`dac`) | 53 |
| – sindicación de prensa (`syndicated_wire` supported) | **45** |
| – (adicional) sin ningún nodo de grado ≥3 | 45 → ~34 |

Los 45 supervivientes: 18 `sustained_amplification`, 12 `unresolved`, 8 `single_source_feed`,
3 `automated_non_malicious`, 3 `synchronized_without_operator`, **1 `cross_account_synchrony`**.
Mediana de 8 cuentas. 12 de ellos tienen una arista de peso ≥10.

## 5. Hipótesis que probé y **quedaron falsadas** (no las toques)

- **«Los clusters son el tema entero».** Falso: el mayor cluster es 11-37 % de los eventos de
  su tema, no el 100 %. El clustering sí discrimina.
- **«Las aristas unen cuentas de meses distintos porтемати».** Falso (§2.1).
- **«Cuentas duplicadas por el mismo actor (bridges, mirrors) inflan el recuento».** Parcialmente
  cierto y **menor de lo que esperaba**: 52 grupos de handles equivalentes
  (`x.bsky.social` = `x.wsocial.eu` = `x.berlin.social.ap.bridged`), 6,9 % de clusters
  afectados y solo **2 HIGH** que declaran 3+ cuentas y son en realidad 2 actores. No justifica
  un gate por sí solo, pero conviene contar actores, no handles.

## 6. Lo que el producto puede decir y lo que no

**Sí, con evidencia:** «N cuentas republicaron la misma pieza en la misma ventana horaria».
Eso es lo que el sistema mide, y es un hecho verificable y útil.

**No:** «detectar FIMI» o «coordinación». Con 1 `cross_account_synchrony` en 1052 clusters,
0criticos y `tight_timing` inerte, la afirmación correcta es **«observamos amplificación
simultánea»**, y la diferencia entre noticia y campaña **no está implementada**.

## 7. El discriminador que falta (propuesta, no aplicada)

Ordenado por relación señal/ruido, todo por medir antes de aplicar (regla del proyecto):

1. **Exigir núcleo para coordinarse**: una arista = amplificación; un núcleo (≥k cuentas
   conectadas con ≥2 pares cada una) = coordinación candidata. Hoy ambos comparten banda.
2. **Reactivar la ráfaga con ventana real**: `bursty()` debe evaluarse en una ventana (p. ej.
   últimas 6-24 h), no como propiedad permanente del histórico de la cuenta.
3. **Contar actores, no handles**: normalizar bridges/mirrors antes del recuento de cuentas
   y del test de dominancia.
4. **Exigir que ninguna cuenta domine** (gate B) y excluir sindicación de prensa.

Cada uno cambia la definición de lo que el observatorio afirma. **Los cuatro son decisión del
dueño**; el orden 1→4 es el de menor a mayor riesgo de cambiar las cifras públicas.
