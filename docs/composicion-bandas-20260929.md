# FIMI — composición real de las bandas y qué significa «coordinación»

**Medición 29-Sep-2026 10:14 UTC** · copia de `data/radar.db` (1052 clusters, 20.016 eventos
miembro) · solo lectura, sin tocar scoring. Guiones en `/tmp/medir_*.py` y
`/tmp/simular_gate_b.py` (server, read-only sobre `/tmp/radar_medicion.db`).

Motivo: es el pendiente nº1 — *qué significa «coordinación» cuando 100 clusters salen en HIGH*.

---

## 1. Dos correcciones a lo que dije antes

**1.1 «El 100 % de HIGH es Bluesky» NO es un hallazgo: es la construcción del grafo.**
El grafo de coordinación solo contiene cuentas sociales (regla dura nº5). Y las cuentas que
forman clusters **no tienen un solo evento de prensa**:

| Prefijo de `events.source` | Eventos |
|---|---|
| bluesky | 95.321 |
| google-news | 29.276 |
| rss | 20.313 |
| telegram | 1.313 |
| reddit | 162 |

Eventos publicados por las 1.700+ cuentas que forman clusters: **27.624, todos bluesky/reddit**.
Y en `cluster_events`: 20.015 filas bluesky + 1 reddit + 0 rss. Un medio republicado no es
miembro de ningún cluster, por diseño. Por tanto «HIGH es 100 % Bluesky» es una tautología
(*el corpus es Bluesky*), no evidencia de sesgo. **Deja de citarse como hallazgo.**

Aviso técnico: `events.source` usa `bluesky` **sin** dos puntos (y `telegram:`, `reddit:` con
dos puntos). Un filtro por prefijo mal escrito da «0 cuentas» y parece un bug de datos.

**1.2 El 100 % de clusters con `single_source_feed` como «explicación principal» era un
artefacto de mi propia consulta.** En `alternative_explanations` ese item se **añade siempre**
índice 0, con estado `ruled_out`/`plausible`/`supported` según la métrica. Leyendo `$[0].code`
sale 1052/1052. La explicación efectiva es la **primera `supported`**, y si no hay, la primera
`plausible`. Con esa lectura:

| Banda | `single_source_feed` | `sustained_ampl.` | `unresolved` | `syndicated_wire` | `cross_account_sync.` |
|---|---|---|---|---|---|
| WATCH (589) | 443 (75 %) | – | 16 | – | – |
| ANOMALOUS (363) | 249 (69 %) | 3 | 18 | 9 | – |
| **HIGH (100)** | **37 (37 %)** | 25 (25 %) | **20 (20 %)** | 10 (10 %) | **1 (1 %)** |

Ningún cluster del corpus entero tiene una explicación `supported` de tipo coordinación
entre cuentas en ráfaga salvo **1**.

---

## 2. Quién domina cada HIGH (medido sobre los miembros, no sobre supuestos)

- 27/100 con **una cuenta ≥55 %** de los eventos del cluster (`dac ≥ 0.55`).
- 42/100 con `dac` entre 0,30 y 0,55 · 31/100 con `dac < 0,30`.
- 17/100 con **un solo dominio** (≥80 %): eco de una pieza o de un enlace.

Las 27 cuentas dominantes son, mayoritariamente, **cuentas-feed o agregadores**:

```
greasydump 0,97 · jazzcomposer 0,84 · anonturk 0,83 · feed.igeek.gamer-geek-news 0,79
papoo7 0,76 · botsocialista 0,76 · news-flows-nl 0,75 · rk70534 0,74 · efe.com 0,71
toebias 0,70 · ai-shop 0,69 · cnn-news 0,69 · news-flows-fr 0,68 · topnewsde 0,67
worldnewsbriefly 0,66/0,63 · kill-bait-es 0,65 · venezuelanewschepa 0,62 · afrique.rfi.fr 0,60
```

Es decir: **una cuenta que rebota noticias estáiendo en HIGH.** El `band_gate` actual solo
mira cuántas cuentas hay (`min_accounts: 3`) y la anomalía; no mira si una de ellas se come
el cluster. Un feed tiene 3+ «cuentas» porque sus bridged posts los replican, y ahí entra
`network_density` como masa.

Reparto temático de los 27: elecciones 8 · oriente_medio 8 · inteligencia_artificial 5 ·
sahel 4 · frontera_sur 1 · energia 1.

---

## 3. Simulación del gate B (no aplicado — decisión del dueño)

Regla propuesta: **HIGH exige que ninguna cuenta domine el cluster** (`dac < 0.55`) **y que no
sea sindicación de prensa** (`syndicated_wire` no `supported`).

| | HIGH |
|---|---|
| actual | 100 |
| – 27 con cuenta dominante | 73 |
| – 10 con sindicación de prensa (unión: 37) | **63** |

Los 63 supervivientes quedan así: 25 `sustained_amplification` (muchas cuentas, ninguna
dominante, ventana >72 h) · 20 `unresolved` · 10 `single_source_feed` (por debajo del umbral
de cuota, el gate no los toca) · 4 sincronización sin operador · 3 automatización no maliciosa
· **1 `cross_account_synchrony`**, la única ráfaga real del sistema.
Temas: oriente_medio 19 · IA 17 · elecciones 9 · eeuu_politica 7.

Efecto colateral que conviene decir: el mismo criterio aplicado a WATCH/ANOMALOUS
(«una cuenta no es coordinación») dejaría el corpus en un 12-15 % de clusters «con
señal» en vez del 56 % que hoy son WATCH. **Eso es un cambio de producto, no un bug**:
o el observatorio publica «coordinación» y casi todo cae, o publica «actividad» y deja de
prometer detección. La segunda es la que ya se cuenta en `sobre.html`.

## 4. Lo que este documento NO dice

No dice que no haya manipulación coordinada en el corpus: dice que **el sistema actual no la
distingue de un feed que reemite**. Con 1 cluster de ráfaga sobre 1052, la afirmación
publicable sigue siendo «observamos amplificación», no «detectamos FIMI».

## 5. Reproducir

```bash
scp medir_efectiva.py simular_gate_b.py deploy@…:/tmp/
ssh deploy@… 'cd /home/deploy/hybrid-fimi-radar && sqlite3 data/radar.db ".backup /tmp/radar_medicion.db" \
  && .venv/bin/python /tmp/medir_efectiva.py /tmp/radar_medicion.db \
  && .venv/bin/python /tmp/simular_gate_b.py /tmp/radar_medicion.db'
```
