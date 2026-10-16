# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/). El proyecto sigue versiones
`v0.X` (prototipo activo). Registra cambios de **método, producto y datos** — no las cifras vivas
del dashboard, que crecen cada ciclo. Fechas en UTC.

## [Unreleased]

### Añadido
- **Síntesis visual («bento») del subcaso «Frontera Sur»** (16-oct, `detection/caso_hibridos_frontera.py`):
  mosaico a golpe de vista en la página del caso (encima de «Lectura de la semana») con **volumen y
  actividad** (eventos núcleo, última semana, ×media 8 sem, z-score), **origen de las fuentes** (redes /
  agregador / prensa directa, en barras), **concentración** (top-5 cuentas, top-3 autores, Gini, URLs
  compartidas) y **polaridad** (heurística, con nota de que mide el vocabulario del texto). Muestra la
  **fecha del ciclo** y el **alcance (solo el núcleo)**; se genera desde los **mismos datos** que el resto
  de la página (sin cifras incrustadas), en **CSS puro, sin JavaScript** y responsive. No toca
  scoring/bandas ni la BD.
- **Subcaso «Frontera Sur»** (`casos/frontera_sur_hibridos/`, en el ciclo de 6 h): expediente de actividad
  militar y presión fronteriza con **escalera epistémica** (mención → afirmación publicada → hecho
  corroborado → interpretación), **episodios** (automáticos + 5 curados a mano con fuente primaria, estado
  de verificación, explicación alternativa y límites), **bloque «Contexto civil»** (escala de la crisis,
  separada del núcleo), **histórico diario** y **API** (`/api/v1/caso/<slug>` + CSV/JSON).
- **Gold set** de validación humana (`detection/caso_goldset.py`): muestra reproducible (seed) +
  herramienta de anotación + evaluador (precisión/recall/F1 por categoría y κ). Resultados del caso:
  **κ categoría 0,37 · tono accuracy 0,80 · relevancia precisión 0,94 / recall 0,57** (un solo anotador).
  Publicado en `metodo.html` §3 bis y `/datos/goldset-frontera-sur.csv`.
- **Licencia CC BY 4.0 + autoría (Miguel Castillo) + «cómo citar» + contacto** en la página del caso.
- **Pseudonimización RGPD** de cuentas personales de redes (`cuenta-<hash>`, sin enlace al perfil;
  salt local fuera del repo). Los medios/feeds se mantienen.
- **Pie con versión git + aviso de proyecto personal** en la página del caso (paridad con el dashboard).
- **Watchdog de OOM** (`scripts/oom_watch.py`, cron `*/30`): avisa por Telegram solo de OOM nuevos.

### Cambiado
- **Concentración de amplificación**: se excluye el **agregador** (Google News) del cálculo por autor
  (antes contaba como una sola cuenta) → en el caso, top-5 **47,5 → 22,6 %**, Gini **0,53 → 0,30**,
  pico top-3 **55,8 → 20,0 %**.
- **Keywords del núcleo** del caso afinadas con **stems** (evaluadas contra la BD real y el gold set).
- **H1** del caso recalculado sobre **serie normalizada por volumen diario + bootstrap por bloques**
  (r 0,50 → 0,33).
- **Cifra de tono** del caso: de «96 %» (muestra no reproducible) a **gold set accuracy 0,80 · κ 0,31**.
- **Página del caso «Frontera Sur» (densidad)**: los dos listados de **episodios** (25 informativos + 5
  curados) pasan a **desplegables** bajo una sola línea («Ver los N episodios · clic para abrir»),
  manteniendo la información **bajo demanda** y en el DOM (indexable). Solo presentación; no toca datos.

### Corregido
- IDs de episodios duplicados → prefijos **`AUTO-` / `CUR-`**; **fecha futura** corregida en un episodio curado.
- «Coordinación: no observada» → **«no medida / no concluyente»**; nota de que «cooperación 0 %» es
  **por diseño del núcleo**, no un hallazgo.
- **Caso «Frontera Sur» — revisión externa (16-oct)**:
  - **Δ de la tabla diaria**: el signo estaba invertido (`−113` donde era `+113`); ahora se calcula por fecha.
  - **Comparabilidad**: se retira del «bento» el `3,7×` y el `z-score`, que contradecían la propia nota
    («no se publica % de subida semanal»); se deja el aviso.
  - **Gold set del tono**: de «anotados a mano» a **«anotados por un modelo, pendiente de revisión humana»**;
    se publican **precisión/recall de la clase «hostil» (0,39 / 0,55)** y la accuracy **solo en filas del
    núcleo (0,57)**, no el 0,80 global (que la muestra no-núcleo inflaba).
  - **H1**: se informa el máximo de la **ventana preinscrita (≤7 d)** —donde **no se sostiene** (p≈0,07)— y el
    máximo a 8 d pasa a **nota exploratoria** (antes se publicaba como «se sostiene»).
  - **Lenguaje**: L5 «Migración como arma» → **«Instrumentalización migratoria»**; hipótesis HC sin «¿anexión?»;
    texto de compartir sin «presión híbrida (Marruecos)» → «Indicadores de actividad».
  - **Coherencia**: autores etiquetados «(periodo)» frente al dato diario; «Contexto militar (fuera del núcleo)»;
    sello «dato» (ciclo) vs «generado»; nota de solapes reescrita.

## [v0.2.1] — 2026-10-10
- **Dataset citable con DOI** (Zenodo) y `CITATION.cff`; export **GEXF/GraphML** por clúster.
- Dashboard aligerado (capa «resto» diferida); **informe visual por tema**; contexto estatal de medios;
  `/llms.txt` para asistentes.

## [v0.2] — 2026-09-21
- **API v1 read-only** (`/api/v1/…`) + OpenAPI; **permalinks estables** (`/c/<lineage_id>`).
- **Tipología** estructural, **explicaciones alternativas**, **auditoría** de señales altas; métricas de grafo.
- Multi‑tema consolidado y **ventana de observación** configurable por tema.

## [v0.1-multitema] — 2026-09-03
- Primera versión multi‑tema: captura por keywords, clustering, **bandas** de amplificación
  (NORMAL / WATCH / ANOMALOUS / HIGH / CRITICAL) y dashboard público.
