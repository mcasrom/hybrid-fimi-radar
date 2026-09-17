# European Hybrid & FIMI Radar

[![CI](https://github.com/mcasrom/hybrid-fimi-radar/actions/workflows/ci.yml/badge.svg)](https://github.com/mcasrom/hybrid-fimi-radar/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/mcasrom/hybrid-fimi-radar/badge)](https://securityscorecards.dev/viewer/?uri=github.com/mcasrom/hybrid-fimi-radar)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

Sistema OSINT **agnóstico al actor** para detectar comportamientos anómalos, coordinación,
amplificación artificial, campañas e infraestructura relacionada con posibles operaciones
de manipulación o interferencia (FIMI — Foreign Information Manipulation and Interference).

> **Regla de oro:** OBSERVACIÓN → ANOMALÍA → COORDINACIÓN → CLUSTER → CAMPAÑA →
> INFRAESTRUCTURA → HIPÓTESIS DE ACTOR → ATRIBUCIÓN CON NIVEL DE CONFIANZA.
> Nunca al revés (no partir de un actor sospechoso).

## Estado en producción

El radar opera en vivo en **`fimi.viajeinteligencia.com`** con **8 temas monitorizados**:

| Tema | Estado |
|---|---|
| Frontera Sur (España-Marruecos) | Producción |
| Política nacional | Producción |
| Política y desinformación EEUU | Producción |
| Oriente Medio (Israel-Irán-Gaza) | Producción |
| Sahel (África Occidental) | Producción |
| Energía (petróleo/gas/precios) | Piloto (en calibración) |
| Elecciones e interferencia electoral | Piloto (en calibración) |
| Inteligencia artificial | Piloto (en calibración) |

- **Pipeline**: captura + detección + scoring ejecutados por cron cada 6 h
  (`scripts/cron_every_6h.sh`).
- **Catálogo de fuentes**: **56 feeds** RSS + 2 plataformas de búsqueda (bluesky, google-news)
  + 4 canales de Telegram + 2 subreddits, cada feed con `bias`/`reliability`/`idioma`/`pais`/
  `analytical_relevance` y nota. El corpus activo ronda los **~54.800 eventos** (ventana 90 d).
- **Dashboard**: HTML estático generado por `detection/gen_fimi_html.py` y servido por
  nginx, reorganizado en **pestañas sticky** (Radar | Transparencia | GitHub) con un
  **hero de centro de situación** (OBSERVAR → DETECTAR → CONTRASTAR + estado en vivo),
  **barra de ecosistema persistente** (viajeinteligencia.com · Herramientas · Blog
  analisis.pruebapublica.com · pruebapublica.com), un **panel de situación "de un vistazo"**
  (tiles KPI: eventos · fuentes · clusters · en alerta · temas; **distribución de clusters
  por banda**; una **tira por tema** con color de banda, score, tendencia y nº de
  clusters — aditivo, no sustituye los diales); y un **gráfico de burbujas global**
  (una burbuja por cluster, agrupadas por tema, con **tamaño = nº de cuentas** y color =
  banda, para una impresión visual global de qué temas concentran más cuentas),
  diales por tema, tarjetas de cluster
  (con "De qué habla", **dominios que amplifican por cluster** — eco de un medio vs red —,
  chips de trayectoria "ecos de 1 pieza"/"coordinación sostenida", export CSV/JSON y
  **borde de color por banda** (rojo CRITICAL · naranja HIGH · ámbar ANOMALOUS · cian
  WATCH) para que la gravedad se perciba a contraluz de la página),
  narrativas, historial, resumen por tema, salud de fuentes, bitácora, **tendencias fuera
  del catálogo** (candidatos a tema con delta 3d), **ejes transversales e indicadores**
  (elecciones/energía/clima/ciber + forma de clusters) y **salto de dominio** en narrativas
  alineadas.
- **Divulgación progresiva (detalle de un tema)**: solo se expanden los **6 clusters de
  mayor score**; el resto (incluidos HIGH/CRITICAL fuera del top-6) va a un bloque plegado
  con **gráfico de barras clicable**. Las secciones **globales** (Narrativas + Historial,
  que no pertenecen al tema) y la **leyenda de componentes** quedan en `<details>` cerrados
  por defecto. Evita paneles de decenas de miles de píxeles cuando un tema tiene muchas
  señales en alerta (frontera_sur: ~61.500 px → ~6.000 px).
- **Hipótesis por cluster (H1–H6)**: cada tarjeta de cluster muestra, bajo la explicación más
  probable, las **6 hipótesis como barras** (orgánico, doméstico, **extranjero**, mediático,
  político, desconocido) con su % — reutiliza `hypotheses_json` de `attribution/attribution.py`
  (cero dato nuevo), con **H3 "operación de influencia extranjera" destacada en rojo**.
- **Panel "de un vistazo" del tema `elecciones`**: cabecera que resume el tema de un golpe —
  **volumen** (eventos · clusters · fuentes), **atribución concluyente** (`0/27` hoy) con una
  franja **"⚖️ señal, no atribución"**, y **menciones de términos por esfera** (rusófono /
  China / EEUU) **etiquetadas en grande como "NO es atribución"**, más los procesos del
  registro. **Sin barras** (solo KPIs): el radar **no puede** decir "cuántos son rusófonos/
  chinos/EEUU" (los clusters salen UNKNOWN) y el panel lo declara, en vez de presentar las
  menciones como si fueran atribución.
- **Piloto vs producción visible**: cada tema lleva su estado a la vista — en las
  tarjetas dial y en las pestañas, un badge **`● Producción`** (verde) o
  **`● PILOTO · en calibración`** (naranja, con pulso suave). Los temas en piloto
  muestran además la frase *"piloto en calibración — lectura con cautela"* en una caja
  naranja destacada y un aviso de riesgo de sesgo en su panel. La animación respeta
  `prefers-reduced-motion`.
- **Rendimiento y robustez**: `frontera_sur` procesa el corpus completo (hoy ~54.800 eventos,
  ~12.300 cuentas). El **pico de memoria** (llegó a ~3,18 GB, con poco margen al OOM en el
  server de 3,7 GB) bajó a **~1,1 GB** y el run de **580 s → 221 s** con dos fixes: (1) los
  centroides TF-IDF de la coordinación se calculan **en sparse**; (2) el ratio de
  *near-duplicates* (`features/content.py`) se computa **por bloques y con umbral al
  instante**, sin materializar la matriz densa m×(N−m) (mismo patrón que las cascadas).
  **Palancas de memoria** en `config.yaml → coordination`: `window_days` (ventana del grafo,
  def. 90) y `tfidf_max_features` (tope de vocabulario, def. 200.000). Toda ampliación de
  feeds pasa por **medir el pico con `/usr/bin/time -v`** antes de darla por buena.
- **Modelo transparente**: la pestaña *Transparencia* expone los pesos del scoring, las
  bandas y la calibración por tema; el dashboard nunca atribuye a un actor sin respaldo.
- **Atribución de tema sin sobre-captura**: la captura por defecto etiqueta todo evento
  RSS bajo `frontera_sur` (tema por defecto), así que clusters de otros temas podían
  inflar su dial. El fix va en **dos capas**: (1) el dashboard **reclasifica cada cluster
  por su tema dominante** (el de más keywords coincidentes en su texto/titular, `view_tema`)
  y muestra una **nota de transparencia** ("de los N clusters que la captura etiquetó en
  este tema, M amplifican contenido de otro tema"); (2) en origen,
  `detection/backfill_tema_contenido.py` re-etiqueta los eventos en `event_temas`
  (INSERT OR IGNORE, aditivo y multi-tema) tras cambiar las keywords de un tema —
  **respetando el gate `filtro`** del tema (no reintroduce lo que el gate rechaza). El dial
  usa la señal **propia** (conservador) y el resumen ejecutivo el top view-clasificado.
- Principios: el sistema **no decide** cerrar/promover temas — solo observa, sugiere y
  avisa; la decisión editorial es siempre humana (ver **Gestión de temas**).

## Temas (multi-tema)

La detección se organiza por **temas**. Cada tema define su catálogo de keywords,
plataformas de captura, estado (`produccion` / `piloto` / `cerrado`) y, opcionalmente, un
scoring propio que sobreescribe los pesos globales (p. ej. `politica_nacional` da más peso
a la anomalía para no marcar coordinación partidista legítima como red inorgánica).

Gestión por CLI (`detection/temas_cli.py`): `alta`, `cerrar`, `estado`, `list`. El cierre
exporta la evidencia a `data/export/`, marca el tema como cerrado (el pipeline lo salta) y
lo registra en la bitácora. `alta --verifica` simula la cobertura de las keywords contra el
corpus antes de crear el tema (evita keywords de registro metodológico que no matchean
titulares reales).

### Fase B — tema Energía (test controlado)

`energia` (piloto) se añadió como **test controlado** de ampliación temática: 3 feeds
especializados (OilPrice, El Periódico de la Energía, pv magazine España) + 8 keywords. Antes de
darlo por bueno se midió el **impacto en memoria** del tema pesado (`frontera_sur`, que carga
el corpus completo): pico **2,46 GB** con el corpus ya ampliado (33.873 eventos, 42 fuentes),
muy por debajo del margen OOM (~3,4 GB). El tema se re-evalúa con datos: si no aporta señal
útil, `temas_cli.py cerrar energia` lo exporta y lo saca del pipeline. **Regla:** toda
ampliación de feeds pasa por medir el pico (`/usr/bin/time -v`) antes de darla por buena.

**Gate de contenido por tema (`filtro`).** Tras el alta inicial se observó que keywords
amplias ("petróleo", "gas natural") etiquetaban posts **políticos** que solo mencionaban la
energía de pasada, y que el dashboard reasignaba a `energia` un **cluster de bot genérico** con
contenido mezclado (Ceuta + OPEP). Fix en dos capas:

1. **Captura** (`collectors/capture.py`): un tema puede declarar `temas.<tema>.filtro` (lista
   de términos fuertes). Un evento solo conserva ese tema si su texto contiene ≥1 término del
   filtro; si se queda sin tema, se descarta. `detection/gate_tema_contenido.py` aplica el
   mismo gate al **histórico** (`--dry` disponible). El **backfill** y `detection/salud_keywords.py`
   (medición de cobertura/ámbito) también aplican el gate, para ser consistentes con la captura.
2. **Vista** (`gen_fimi_html.py` → `view_tema`): al reasignar un cluster por contenido se
   exige (a) que pase el `filtro` del tema y (b) **cobertura ≥50%** de sus eventos, para no
   atribuir a un tema un cluster de bot con contenido mezclado. La cobertura se mide con la
   **intersección `keywords ∩ filtro`** del tema (si está vacía, las keywords): así un cluster
   de Ceuta que menciona "Irán"/"Gaza" de pasada no se reasigna a `oriente_medio`, y un
   `filtro` más ancho que las keywords (energia) no dispara falsos positivos.

Resultado real: `energia` pasó de 705 a **606 eventos** y de 11 a **6 clusters**, todos
energéticos (OPEP/Brent/gas/Ormuz); el cluster mezclado volvió a su tema real (frontera_sur).

### Cobertura electoral — Alemania y Suecia (14/09/2026)

Para el capítulo **Election Threat Landscape** (elecciones de Alemania —Länder, sep-2026— y
Suecia —Riksdag, 13-sep-2026—) se añadieron **6 feeds** de discurso doméstico con balance
por país (público / centro-izq / centro-der), todos verificados HTTP 200 con UA de navegador:
**Tagesschau (ARD), Der Spiegel, FAZ** (Alemania) y **SVT Nyheter, Dagens Nyheter, Svenska
Dagbladet** (Suecia). Catálogo entonces: **40 feeds** (fr 15 · es 9 · en 9 · de 3 · sv 3 · ar 1;
hoy **44** tras añadir las fuentes de esfera, ver abajo).
**EEUU no añade feeds** (midterms nov-2026): se cubre con las keywords de `eeuu_politica` +
feeds existentes, para no engordar el sumidero por defecto `frontera_sur`. Detalle y probaturas
en [`docs/FUENTES.md`](docs/FUENTES.md).

### Fuentes de esfera (rusa/china) — 15/09/2026

Para poder cruzar **narrativas de esfera estatal** en los temas se añadieron **4 feeds**
estatales verificados (HTTP 200 + RSS): **TASS (EN)** y **RIA Novosti (RU)** (Rusia) ·
**CGTN (EN)** y **Global Times (EN)** (China), todos con `bias: state`, `reliability: mixed`,
`pais` RU/CN y nota "vigilar como fuente FIMI". **Catálogo 40 → 44 feeds** (8 estatales, con
RT en Español y las agencias del Sahel). **Nota honesta**: al ser **RSS**, estas fuentes **no
entran al grafo de coordinación** → aportan **cobertura y catalogación de dominio/esfera**, no
señal de coordinación por sí solas (su contenido actual, además, es general —BRICS, ciencia,
deportes—, no electoral).

### Fuentes adicionales (17/09/2026)

Se amplió el catálogo con dos fuentes relevantes para la cobertura transversal:

- **Sputnik Mundo** (`noticiaslatam.lat/export/rss2/archive/index.xml`):
  agencia rusa en español. `bias: state`, `idioma: es`, `pais: RU`,
  `analytical_relevance: alta`. Única fuente estatal rusa en español
  accesible por RSS; cubre geopolítica, conflicto Ucrania-Rusia y
  narrativa estatal. Sancionada por la UE en 2022 — vigilar como
  narrativa FIMI, no usar como verdad absoluta.
- **Hespress** (`hespress.com/feed/ar/`): medio marroquí con versión
  árabe genuina (`<language>ar</language>`). `idioma: ar`, complementa
  la cobertura del norte de África y el mundo árabe.

**Global Times (EN) — feed migrado (17/09/2026)**: el feed nativo
(`globaltimes.cn/rss/outbrain.xml`) solo actualizaba hasta **ago-2026** (el
`lastBuildDate` sí era de hoy, pero los ítems no) y sus sub-feeds
(`/rss/china.xml`, `/rss/world.xml`, `/rss/opinion.xml`, `/rss/business.xml`…)
devuelven **404**. Se sustituye por **Google News site-scoped**
(`news.google.com/rss/search?q=site:globaltimes.cn`), verificado con 100 ítems y
último del mismo día (antes: 0/1 eventos y 25 d sin actualizar). Mismos metadatos
(`bias: state`, `reliability: mixed`, `pais: CN`, nota "vigilar como fuente FIMI").

**Catálogo: 55 → 56 feeds** (Global Times migrado, no añadido).

### Piloto IA — tema Inteligencia artificial (16/09/2026)

`inteligencia_artificial` (piloto) monitoriza narrativas de IA (modelos, agentes,
regulación, deepfakes) con `filtro` de 9 términos + 11 keywords. Se dota de **8 feeds
específicos** — TechCrunch AI, Ars Technica, MIT Technology Review, AI News, Numerama,
ActuIA, Xataka, El País Tecnología — **+3 añadidos el 16/09** (The Verge AI, The Decoder,
Wired AI, los tres verificados HTTP 200 con contenido IA claro). **Catálogo 52 → 55 feeds**.

- **Nota honesta**: los feeds tech generales (Xataka/Ars/Numerama/El País Tec) rinden poco
  para el tema (~4-8% de sus eventos pasan el filtro, frente a 28-40% de los específicos)
  porque su contenido no es siempre de IA y el `filtro` no incluye "AI". Se **descartó**
  añadir "AI" como keyword: capturaría ~+31% de eventos pero con falsos positivos (italiano
  "ai", portugués "aí") y conflicto con mención incidental.
- **Fase B medida**: `run_fimi --tema frontera_sur` con el corpus ampliado → pico **1,6 GB**
  (margen OOM ~3,4 GB intacto), exit 0.

### Capítulo Election Threat Landscape (opción B, registro)

`detection/elecciones.py` es una capa **transversal** (solo lectura) dirigida por un
**registro de elecciones** (`data/elecciones.yaml`, una fila por proceso: `pais`,
`nombre`, `fecha`, `idioma`, `keywords`, `estado`). Para cada elección calcula la
**fase** desde su fecha (modelo EEAS: meses antes / mes electoral / 72 h / post), cruza
el corpus por país+proceso y reporta **cobertura** (eventos/fuentes), **actor**
(rusófono/China/EEUU) y objetivo **5D** por señal léxica, y en qué temas aterriza. Es
**descriptivo, sin atribución**: cuenta y clasifica por palabras, no afirma autoría; una
cobertura baja indica falta de feeds de ese país, no ausencia de campaña. Se muestra como
**card visual** en la pestaña **Transparencia**: una **línea de tiempo (SVG)** con cada
elección (punto = elección, color = fase, línea roja = hoy) y, por elección, una **barra de
cobertura** (eventos) + la **señal de coordinación** (cuántos de sus eventos forman parte de
un **cluster detectado** — amplificación coordinada — y el mayor implicado) + **chips** de
actor (rusófono/China/EEUU), 5D y temas de aterrizaje.
Añadir una elección = una fila (o
`detection/elecciones_cli.py alta --pais … --nombre … --fecha AAAA-MM-DD --keywords "…"`;
`list` y `cerrar` para gestionar). No toca captura ni scoring (coste ~0 de memoria).

**Opción B (HECHA, 15/09/2026)**: `elecciones` es ahora **tema propio** (piloto) con `filtro`
de contenido electoral (≥1 término real: `elecciones`, `electoral`, `urnas`, `midterms`,
`fraude electoral`, `election interference`…; el `filtro` evita falsos positivos como siglas
sueltas tipo `afd` del boletín meteorológico "Area Forecast Discussion"). Así `run_fimi`
**clusteriza específicamente** el contenido electoral en vez de absorberlo en `frontera_sur`.
La card añade el bloque **"Detección: clusters electorales (tema `elecciones`)"** con los
clusters propios (score/banda · cuentas · eventos · URLs · titular), y la señal de
coordinación por elección cuenta **solo** los clusters de ese tema. Verificado en el ciclo
real (00:44 UTC): **17 clusters**, top **76/100 HIGH** (Riksdag Suecia; interferencia
electoral EEUU).

**Procesos de alto valor (17/09/2026)**: el registro se amplió a **10 procesos** con los de
mayor interés para injerencia/FIMI (calendario OSCE): **Rusia** (legislativas 18-20 sep),
**Letonia** (parlamentarias 3 oct), **Bosnia y Herzegovina** (generales 4 oct), **Brasil**
(generales 4 oct), **Bulgaria** (presidenciales 25 oct) y **Serbia** (parlamentarias 25 oct)
—además de Alemania×2, Suecia y EEUU—. Para que su **discurso doméstico** pase el gate, se
añadieron **7 términos nativos** al `filtro` y a las keywords del tema (`выборы`, `госдума`,
`vēlēšanas`, `saeima`, `izbori`, `eleições`, `избори`); filtro 23→30, keywords 24→31.
Backfill +9 eventos (90 d), gate 0 fallos, `run_fimi` 60→65 clusters.

**Segundo nivel (15/09/2026)**: el bloque de detección clasifica cada cluster como
**«menciona interferencia»** (su texto contiene términos de `temas.elecciones.senal`:
desinformación, injerencia, bots/trolls, fraude, coordinación inauténtica…) o
**cobertura electoral** (ruido esperable de campaña), y lista **señal primero**. Es un
**filtro léxico**: marca clusters que *mencionan* ese léxico — lo que **incluye cobertura
SOBRE** la interferencia (p. ej. un reportaje «…amid election interference fears» sale
marcado). **«Menciona interferencia» ≠ «operación detectada»**, y así se etiqueta en la
card. Un eco de «los socialdemócratas ganan Suecia» deja de encabezar la detección
(*cobertura*). Resumen visible: *«de N clusters: X mencionan interferencia · Y cobertura»*.
Es **clasificación, no captura**: no recorta el tema.

**Test real T2 (15/09/2026)**: sobre los **36 clusters reales** del tema, el radar **ve
coordinación real** (top 74/100 HIGH con **7 cuentas**; otros 4 cuentas) y **no infla**
(los clusters de 2 cuentas quedan capados a WATCH 39 por `scale_floor`/`origen_unico`;
reparto del 2º nivel: **13 mencionan interferencia / 23 cobertura**). **No atribuye**:
todos los top dan **H6 «sin evidencia concluyente» (0,91-0,96)** → coherente con 0/36
concluyentes.

## Ciclo de vida y gobernanza

El radar **no decide**: observa, sugiere y avisa; toda transición de estado la toma una
persona y queda en la bitácora. Los temas nacen en **piloto** y pasan a **producción**
solo tras superar una ventana de validación; el cierre es siempre una **sugerencia**.

- **Promoción (piloto → producción)**: `detection/check_promocion.py` exige ≥ **72 h** de
  observación y ≥ **8 ciclos** de snapshot sin errores (un error nuevo **reinicia** la
  ventana). Al cumplirse, avisa por **Telegram** y activa el botón **«⬆️ Promover»** del
  panel (o `temas_cli.py --estado <tema> produccion`). El dashboard muestra
  «✅ lista para producción».
- **Cierre (sugerencia)**: `detection/check_cierre.py` marca **candidato a cierre** si el
  tema acumula **<2 hallazgos/día** en 21 días (tras ≥14 de operación) o si un piloto lleva
  **>90 días** sin promocionar — salvo que haya señal clara (último cluster ≥60). Avisa por
  Telegram + bitácora; el cierre real (`temas_cli.py --cerrar`) exporta la evidencia,
  detiene el pipeline del tema y se puede **reabrir**.
- **Ventanas por tema (ciclos largos)**: los umbrales anteriores son **defaults**. Un tema
  puede declarar `temas.<tema>.ventanas` en `config.yaml` (`promocion_h`, `promocion_ciclos`,
  `cierre_ventana_dias`, `cierre_findings_por_dia`, `cierre_min_dias`, `cierre_piloto_dias`,
  `cierre_calendario_dias`). Pensado para temas de **ciclo largo**: `elecciones` usa promoción
  de **30 días** (no 72 h) y cierre a **90 días**, y con `cierre_calendario_dias: 120` **no se
  sugiere cerrar** si hay una elección del registro (`data/elecciones.yaml`) a ±120 días — el
  tema puede estar **dormido entre procesos**, no muerto. Sin el bloque, se usan los defaults
  globales (env `FIMI_*`).
- **Panel de administración**: muestra el **progreso de la ventana** por tema
  (`X/<ventana> h · N/<ciclos> ciclos · errores`), la señal y los botones Promover / Cerrar / Reabrir.

Detalle completo (criterios, umbrales y variables configurables):
[`docs/GOBERNANZA.md`](docs/GOBERNANZA.md). En la web:
[**Manual de operación**](https://fimi.viajeinteligencia.com/operativa.html) (usuario + admin).

## Validación (test sintético FIMI)

Generador sintético con 6 escenarios (tests/generate_synthetic.py):

| Escenario | Recuperación |
|---|---|
| B (campaña doméstica) | **100%** |
| C (campaña extranjera) | **100%** |
| F (atribución desconocida) | **100%** |
| A (orgánico normal) | 0% (0 falsos positivos) |
| D (falsa alarma) | 0% (correctamente no disparada) |
| E (evento viral orgánico) | parcial (correcto: viral ≠ coordinación) |

**ARI = 1.000** (separación perfecta de los clusters coordinados) y **0 falsos
positivos** en los grupos orgánicos (A/D).

La validación está **automatizada como gate de CI** (`tests/test_synthetic_ari.py`):
genera los 6 escenarios, ejecuta el detector real (features → anomalías →
coordinación → clustering de componentes conexas) **sin base de datos ni filtro de
tema**, y exige **ARI ≥ 0.9** sobre los grupos coordinados (B/C/F) y una **tasa de
falsos positivos ≤ 1 %** en los orgánicos (A/D; el evento viral E puede clusterizar
parcialmente, que es el resultado correcto de *viral ≠ coordinación*). Medición
actual: **ARI = 1.000**, FP = 2/1050 (0,19 %).

## Validación externa (EUvsDisinfo)

Cruza la vista activa del radar con el dataset de campañas documentadas de EUvsDisinfo
(`data/euvsdisinfo_base.csv`, Zenodo `10514307`, 18.249 casos / 10.682 de desinformación /
1.311 dominios documentados; se auto-descarga a `data/`, gitignored). Uso:
`tests/validacion_externa.py --json`.

El dataset **incluye `article_language`**, así que la validación puede restringirse a un
idioma con **`--lang spanish`** (más comparable para un radar de contenido en castellano):
243 casos / 17 dominios documentados en español, dominados por Sputnik Mundo
(`mundo.sputniknews.com`, `sputniknews.lat`) y RT en Español (`actualidad.rt.com`) — narrativa
Ucrania/Rusia. El radar **sí captura RT en Español** (360 eventos) pero no Sputnik Mundo.

Resultados reales sobre la vista activa (último snapshot **por tema**, 90 d):

- **Precision 8.5%**: de los **199 clusters con score ≥ 60**, **17** amplifican al menos un
  dominio documentado (`actualidad-rt.com`, `breitbart.com`, `counterpunch.org`, `freitag.de`,
  `aa.com.tr`…). El resto amplifica prensa mainstream no documentada.
- **Recall 0.0%**: hay **4 fuentes documentadas capturadas** (RIA Novosti, RT en Español,
  SVT Nyheter, TASS; 400/567/143/267 eventos) y **ninguna** entra en una señal (narrativa o
  cluster).

> **Corrección (17/09/2026)**: hasta esta fecha la precisión se reportaba como **0.0%**. Era un
> **bug**: la «vista activa» usaba `created_at = MAX(global)`, pero cada tema se procesa por
> separado y `created_at` se escribe por cluster → solo capturaba el último tema/segundo. Ahora
> se toma el **último snapshot por tema** (tolerancia 1 h). Con la vista correcta la precisión
> real es **8.5%** (global) y **3.0%** con `--lang spanish`.

**Ejecución automática (sin intervención, sin claves):** `detection/validacion_auto.py`
refresca el dataset si está viejo (>30 d), corre la validación en global y en castellano, guarda
el informe en `data/validacion/auto_*.json` y avisa por Telegram **solo si cambia** el resultado
(patrón on_change). Es un *tripwire*: vigila que el cruce siga corriendo y que ninguna fuente o
dominio documentado aparezca en las señales.

**Interpretación (según el docstring del script):** el recall 0 es un resultado correcto,
no un fallo — los feeds RSS no participan en el grafo de coordinación (por diseño, solo
redes sociales) y los titulares de RT no se replican en ≥ 3 fuentes del catálogo; un radar
de coordinación no debe señalar RT solo por ser RT, sino cuando su narrativa se propaga.
Además, EUvsDisinfo es histórico (2015-2023, foco Ucrania/Rusia), no cubre los temas activos
del radar (Ceuta/Marruecos/España/EEUU/Oriente Medio), por lo que el benchmark valida la
**mecánica** del cruce, no la ausencia de campañas. La evidencia real de que el detector
funciona está en la validación sintética (ARI 1.000) + este cruce de dominios.

## Pruebas y CI

- **Tests unitarios** (`tests/test_units.py`): scoring (bandas, pesos con override por
  tema, escala completa), `normalizer/clasificar.py` (match por límite de palabra) y
  `clustering/clustering.py` (prefijo de label por tema + componentes conexas).
- **Gate ARI** (`tests/test_synthetic_ari.py`): separación de las campañas inyectadas
  (ver *Validación* arriba).
- **Restore-test de backup** (`detection/restore_test.py`): restaura el backup más
  reciente a un temporal y verifica `PRAGMA integrity_check`, las tablas clave y el
  cuadre de conteos con la BD viva. **No toca producción**:
  `python detection/restore_test.py [--backup ruta] [--json]`.
- **CI** (`.github/workflows/ci.yml`): `compileall` + `ruff` + `bandit` (advisory) +
  `pytest` con **cobertura** (gate `--cov-fail-under=50` sobre los módulos con tests).

## CTA cruzado con el blog (analisis.pruebapublica.com)

Las tarjetas de los temas Frontera Sur, Política nacional y
Política EEUU enlazan al análisis editorial correspondiente del blog (y viceversa: los posts
del blog llevan un bloque "Este tema, en vivo: Radar FIMI" con deep-link al tema por hash
`#<tema>`). Generado en `detection/gen_fimi_html.py`.

## Instalación y uso

```bash
cd hybrid-fimi-radar
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Generar datos sintéticos de validación
python tests/generate_synthetic.py

# 2. Ejecutar el pipeline de un tema (detección + scoring + clusters + persistencia)
python detection/run_fimi.py --tema frontera_sur

# 3. Regenerar el dashboard estático
python detection/gen_fimi_html.py
```

> En producción el pipeline se dispara por cron cada 6 h sobre todos los temas activos de
> `config.yaml`; el dashboard resultante se publica en `/var/www/fimi/index.html`.

## Arquitectura

```
COLLECTORS → RAW → NORMALIZER → FEATURES → DETECTION → CLUSTERING → SCORING
→ ATTRIBUTION → SQLITE → REPORT → DASHBOARD
```

```
hybrid-fimi-radar/
├── config.yaml             # Temas, keywords, pesos, bandas, fuentes (configurables)
├── collectors/             # captura (Bluesky/Telegram/RSS/GoogleNews/Reddit/Mastodon)
├── normalizer/             # ingest + schema SQLite
├── features/               # características temporales/contenido/bot-signals
├── detection/
│   ├── run_fimi.py         # pipeline de detección por tema
│   ├── gen_fimi_html.py    # dashboard estático (pestañas sticky)
│   ├── scoring.py          # scoring ponderado + escala/escala por tema
│   ├── clustering/         # componentes conexas + evidencia por cluster
│   ├── attribution/        # atribución con confianza + hipótesis H1-H6
│   ├── radar_trend.py      # dial de estado (fuente de verdad HOY vs hace 48h)
│   ├── salud_tema.py       # score compuesto de salud por tema
│   ├── temas_emergentes.py # tendencias fuera de catálogo (candidatos + delta 3d)
│   ├── indicadores.py      # ejes transversales (elecciones/energía/clima/ciber) + forma de clusters
│   ├── transversal.py      # pulso transversal (¿migra una narrativa de dominio entre semanas?)
│   ├── resumen_tema.py     # síntesis por tema (sin IA)
│   ├── health_fuentes.py   # salud y fiabilidad de fuentes (bias/reliability/corroboration)
│   ├── narrativas_alineadas.py  # cluster-of-clusters cross-tema + salto de dominio (TF-IDF + coseno)
│   ├── whois_signal.py     # señal de dominio (RDAP) para clusters de alta banda
│   ├── export_evidencia.py # export CSV/JSON de la evidencia de un cluster
│   ├── bitacora.py         # bitácora de temas (inicio/cambio/cierre/sugerencia)
│   ├── check_cierre.py     # candidatura a cierre (solo sugiere, no decide)
│   ├── check_promocion.py  # validación de piloto→producción (ventana por tema, ciclo BD)
│   ├── check_ingesta.py    # alerta si el cron se salta la captura
│   ├── salud_keywords.py   # ¿captura cada tema su ruido real? (patrón "tema ciego")
│   ├── backfill_tema_contenido.py  # re-etiqueta por contenido tras cambiar keywords
│   ├── gate_tema_contenido.py      # aplica el gate `filtro` de un tema al histórico
│   ├── check_sistema.py    # check médico integral del pipeline (BD/config/frescura)
│   ├── mantenimiento.py    # retención >90 d + backup gzip + VACUUM
│   ├── radar_bot.py        # bot de Telegram (long-poll)
│   ├── email_api.py        # API HTTP de suscripción email + /api/export + /api/admin
│   ├── email_digest.py     # digest semanal por email
│   ├── notify_subs_telegram.py  # aviso Telegram on_change
│   ├── notify_fuentes.py   # alerta si una fuente empeora
│   ├── temas_cli.py        # alta/cierre/estado de temas (PILOTO→prod)
│   ├── schema_suscripciones.py / schema_feedback.py / schema_bitacora.py
│   └── pipeline.py         # (legacy, sin uso)
├── tests/                  # generador sintético + validación
├── reports/                # informes Markdown (gitignored)
└── docs/                   # TAXONOMIA.md, SCORING.md, ATRIBUCION-LIMITACIONES.md, TRAZABILIDAD.md, FUENTES.md
```

## Modelo de datos (SQLite)

`sources` · `events` · `event_temas` · `narratives` · `clusters` · `indicators` ·
`assessments` · `cluster_events` · `evidence` · `findings` · `feedback` · `bitacora` ·
`suscripciones` (esquema en `normalizer/schema.py` y módulos `schema_*.py`).

## Transparencia del scoring

El score de coordinación por cluster combina componentes 0-100 (sincronización, contenido
similar, amplificación, infraestructura, densidad de red, anomalía) con una **escala** de
cuentas (piso de masa, tope por banda y bonus) y es calibrable **por tema**. Todo esto se
expone en la pestaña *Transparencia* del dashboard y se documenta en `docs/SCORING.md`.

## Taxonomía, tendencias y ejes transversales (Fase A)

Capa de estructura temática y lectura transversal, **sin captura nueva ni cambio en el
scoring** (coste ~0, sin riesgo de memoria). Documentada en `docs/TAXONOMIA.md`.

- **Taxonomía**: cada tema pertenece a familias transversales (A crisis · B instituciones ·
  C recursos · D tecnología · E sociedad). Se distingue **tema** (superficie de observación)
  de **narrativa** (relato que puede cruzar temas).
- **Tendencias fuera del catálogo** (`temas_emergentes.py`): eventos que no matchean ninguna
  keyword del catálogo, agrupados por término, con **delta temporal 3d vs 3d** (▲ subiendo ·
  ▼ bajando · 🆕 nuevo · ▬ estable). Ranking por volumen sostenido 14d; la tendencia es
  anotación. Candidatos a keyword/tema — el sistema no añade nada.
- **Salto de dominio** (`narrativas_alineadas.py`): un grupo de clusters que cruza **≥2
  familias** lleva el chip *⚡ salto de dominio* (misma narrativa viajando entre ámbitos).
- **Ejes transversales e indicadores** (`indicadores.py`, card `#ejes-transversales`):
  lentes que cruzan temas (Elecciones e interferencia democrática · Energía/precios ·
  Clima/agua/incendios · Ciberseguridad) contando volumen, fuentes y en qué temas aterrizan;
  y **indicadores de forma** de los clusters (eco de 1 pieza / ráfaga / coordinación
  sostenida), separados del score. **Un eje no es un tema**: es una dimensión compartida que,
  con volumen alto y multi-fuente, puede justificar un tema propio (decisión humana).

## Pulso transversal (Fase C)

`detection/transversal.py` (card `#pulso-transversal`) hace observable el análisis
transversal que pide la matriz de temas: una misma narrativa puede desplazarse entre
ámbitos (`conflicto → energía → economía → migración → política`). Para cada **narrativa
ancla** (actores/temas que viajan: petróleo, ormuz, ucrania, gaza, migración, elecciones…)
calcula, por semana y sobre el texto de los eventos, en qué **familia temática** (A–E) aterrizan
sus eventos, y marca:

- **◧ multi-dominio** — el ancla vive en ≥2 familias a la vez.
- **⚡ migra de dominio** — la familia dominante cambió entre las dos semanas más recientes
  comparables (7 d vs 7 d; umbral adaptativo por ancla para no leer la rampa inicial del corpus).

**Descriptivo, no causal**: no afirma que A causó B, solo que la conversación sobre un ancla
pasó de concentrarse en un dominio a otro. Los eventos que no matchean ninguna keyword no
cuentan como dominio (bucket *"sin clasificar"*). El sistema no decide: señala dónde mirar.

## Suscripciones (Telegram / email)

Esquema centralizado en una única tabla para todos los canales:
`suscripciones (id, canal, destino, temas, frecuencia, ultimo_estado, fecha_alta, confirmado)`.
Crea la tabla con `python detection/schema_suscripciones.py`.

- **Telegram**: bot dedicado (long-poll, `detection/radar_bot.py`, handle `@RadarFIMI_bot`)
  con `/radar`, `/mis` y `/baja`. El envío de avisos lo hace `detection/notify_subs_telegram.py` (añadido al cron
  6h): solo notifica cuando un dial cambia de estado (on_change), comparando contra
  `ultimo_estado` — sin spam.
- **Email**: backend HTTP de stdlib (`detection/email_api.py`) + Resend (dominio
  viajeinteligencia.com verificado en `newsletter@viajeinteligencia.com`), doble opt-in, narrativa por proyecto (FIMI digest B `58b1e0a` con score/high/banda/salud/narrativas/top link real; blog separado en `analisis.db` via `scripts/send_blog_newsletter.py` 5 ultimos),
  frecuencia semanal y enlace de baja; digest en `detection/email_digest.py`.
- **Estado del dial**: fuente de verdad compartida en `detection/radar_trend.py` (mismo
  criterio HOY vs hace 48h que los diales de la vista resumen).

El token del bot se lee de `FIMI_TELEGRAM_BOT_TOKEN` (env/`.env`), nunca hardcodeado; `.env`
está en `.gitignore`. Los endpoints `/api/*` están protegidos con rate-limit y los de admin
requieren `x-admin-secret`.

## Panel de administración y gestión de temas

El panel del administrador vive en **`/admin.html`** (estático en `/var/www/fimi/`, `noindex`;
no está en el repo) y se autentica con `x-admin-secret` (`FIMI_ADMIN_SECRET`). Muestra
votos por tema, sugerencias, suscriptores por proyecto y **Gestión de temas**.

Incluye un módulo **"Tendencias y temas hot"** (`GET /api/admin/tendencias`, read-only):
**temas hot** por momentum (hallazgos 3 d vs 3 d anteriores), **candidatos a tema nuevo**
(volumen fuera del catálogo) y **ejes transversales**; con `?full=1` añade la **migración de
dominio** (bloque más pesado, ~15 s). Reutiliza los módulos de Fase A/C; **ligero por
defecto** y el bloque de migraciones se carga bajo demanda desde el panel.

La gestión de temas refleja el principio *"el sistema no decide"*: los controles solo se
activan cuando el propio radar ya marcó la señal, y la acción la ejecuta el administrador.

| Acción | Cuándo aparece | Endpoint (auth `x-admin-secret`) | Efecto |
|---|---|---|---|
| ⬆️ **Promover** a producción | tema `piloto` con `ready` (ventana 72h / 8 ciclos) | `POST /api/admin/tema-estado` | `piloto → produccion` |
| 🗄️ **Cerrar** | sugerencia de `check_cierre` (o manual) | `POST /api/admin/tema-cerrar` | exporta evidencia, `cerrado`, bitácora |
| ↻ **Reabrir** | tema `cerrado` / `candidato_a_cierre` | `POST /api/admin/tema-estado` | `→ piloto` |
| ↩︎ **A piloto** | tema en producción | `POST /api/admin/tema-estado` | `produccion → piloto` |

- `GET /api/admin/temas` devuelve el estado de cada tema + señales (`ready`,
  `candidato_cierre`). El dashboard (vista resumen) muestra en la tarjeta del tema un
  badge **"✅ Lista para producción · gestionar"** o **"🗂 Candidata a cierre · gestionar"**
  que enlaza al panel: la tarjeta comunica, la acción se ejecuta autenticada.
- Las acciones reutilizan `detection/temas_cli.py` (`--no-regen`) y lanzan la regeneración
  del dashboard **en segundo plano** (`subprocess.Popen`, con guardia para no solapar
  regeneraciones). Todo queda en la **bitácora**.
- El HTML público nunca contiene el secreto: se pide al entrar y se guarda solo en la
  sesión. Se corrigió además un bug de visibilidad en `admin.html` (`entrar()` invertía el
  panel) que impedía ver el panel tras introducir el secreto correcto.

## Export de evidencia por cluster

Para auditoría OSINT, `detection/export_evidencia.py` permite descargar los textos, fuentes
y URLs de un cluster en CSV o JSON (`--cluster <label> --fmt csv|json`), o en el dashboard
(los links "Exportar evidencia" de cada tarjeta). Recurso público: los datos ya eran
visibles en las tarjetas; el export solo los facilita.

## API pública v1 (read-only)

La misma señal del dashboard, en JSON autodescriptivo, para reutilizarla sin scrapear
el HTML. Servida por `detection/email_api.py` (stdlib) detrás de nginx (`/api/*`,
rate-limit 20 req/min por IP) y con CORS abierto para lectura.

| Endpoint | Descripción |
|---|---|
| `GET /api/v1` | Índice de endpoints + bloque `meta` (versión, snapshot, aviso) |
| `GET /api/v1/temas` | Resumen por tema: nº clusters, en alerta (≥60) y top (score/banda) |
| `GET /api/v1/tema/<slug>` | Clusters del tema con componentes 0-100, confianza y atribución |
| `GET /api/v1/cluster/<label>` | Cluster completo + evidencia (eventos) |
| `GET /api/v1/openapi.json` | Especificación OpenAPI 3.0 |
| `GET /api/v1/health` | Estado del servicio |

Cada respuesta incluye `meta` (programa, versión, `generado_utc`, `snapshot: true`,
`aviso` y `replay` con pesos/bandas/ventana para reproducir el score) y, por cluster,
`banda`, `components`, `confidence`, `attribution`, `hypotheses` y `disclaimer`
("señal de comportamiento, no atribución").

**Cautela**: los `cluster_label` se regeneran en cada ciclo (cada 6 h) y **no son
estables**; cada respuesta es una **foto del último ciclo** (`meta.snapshot=true`).
No expone endpoints de administración ni datos personales.

**Errores**: todas las respuestas de error son **JSON** con `{"error": "...", "code": N}`
— `400` parámetros inválidos, `404` no encontrado, `405` método no permitido (con cabecera
`Allow`), y `414`/`500`/`505` de protocolo/servidor. Nunca se devuelve HTML ni una traza.
`HEAD` está soportado (mismas cabeceras que `GET`, sin cuerpo).

## Contexto de interpretación en las tarjetas de cluster

Cada cluster se presenta con bloques de contexto que ayudan al analista a no sobreleer la
señal (todo solo lectura; no altera el scoring):

- **"De qué habla este cluster"**: los 2-3 titulares más repetidos de sus `cluster_events`,
  con enlace a la fuente y frecuencia (xN).
- **"Dominios que amplifican (N)"**: cuántas cuentas distintas comparten cada dominio,
  para distinguir visualmente el **eco de un mismo medio** (p. ej. 2 cuentas compartiendo
  eldiario.es) de una **red que amplifica fuentes variadas** (eldiario·51, elpais·19, …).
- **Chips de trayectoria**: "ecos de 1 pieza" (varias cuentas comparten la MISMA URL) vs
  "coordinación sostenida" (la misma red vierte muchas piezas en ≥24 h) — calculado de la
  diversidad de URLs y la ventana temporal del cluster.
- **Guardia de interpretación** en HIGH/CRITICAL: la banda es señal conductual de
  coordinación, no atribución de actor ni prueba de orquestación.
- **Anotación "recortado por escala"**: los clusters de <3 cuentas limitados por el piso de
  masa a banda WATCH muestran el motivo, para que los 39/100 repetidos no parezcan el mismo
  hallazgo clonado.

## Araña de componentes por tema (radar)

En el **detalle de cada tema**, bajo la leyenda "Cómo leer los componentes (0-100)", se
muestra una **araña (radar) de 4 ejes** con los componentes del tema a escala 0-100:
**Coordinación · Anomalía · Infraestructura · Densidad**. Dos polígonos:

- **media del tema** (naranja): promedio de los componentes de sus clusters;
- **cluster top** (azul discontinuo): los componentes del cluster de mayor score.

Solo lectura: se calcula del `assessment` ya cargado (cero dato nuevo, cero scoring). Da
una lectura de un vistazo del **perfil del tema** (qué componente pesa). Generado por
`render_radar_componentes()` (SVG inline, sin librerías).

## Atribución (separada del detector)

Taxonomía neutra: UNKNOWN / DOMESTIC / FOREIGN_STATE / FOREIGN_NON_STATE /
TRANSNATIONAL_NETWORK / PROXY / MIXED / UNDETERMINED.

Confianza: NO_ATTRIBUTION / LOW / MEDIUM / HIGH. La ausencia de atribución es
**un resultado válido**. Nunca se usa ideología como indicador de amenaza.
Límites y reglas de lectura en `docs/ATRIBUCION-LIMITACIONES.md`.

## Hipótesis alternativas (anti sesgo de confirmación)

H1 orgánico viral · H2 campaña doméstica · H3 operación extranjera ·
H4 amplificación mediática · H5 campaña política · H6 desconocido.

## Honestidad metodológica

- El sistema **no busca confirmar** que "Rusia/China/Marruecos/EEUU/izquierda/derecha"
  están detrás de una campaña. Dice lo que observa, lo que es estadísticamente anómalo,
  las evidencias de coordinación y las hipótesis posibles con su nivel de confianza.
- "No existe evidencia suficiente para atribuir a un actor extranjero" es una conclusión válida.
- Sin LLM como componente principal del detector (solo estadística clásica, explicable).
- **Líneas base robustas**: no se declara "nuevo máximo del tema" con menos de 14 días de
  historia; con bases más cortas se etiqueta como *máximo de la ventana observada*.


## Gobernanza de datos y salvaguardas

- **Qué se almacena**: solo información pública —identificadores de cuenta de redes sociales
  (Bluesky, Telegram, Reddit, Mastodon), el texto de sus publicaciones, URLs y marcas de
  tiempo—. No hay contenido privado ni perfilado de personas.
- **Qué no entra**: los feeds RSS de medios no participan en el grafo de coordinación; no se
  monitorizan cuentas privadas ni se rastrean individuos (el objeto es el **comportamiento**
  de coordinación, no la identidad).
- **Criterios**: se incluyen cuentas públicas que publican sobre los temas; se excluyen bots
  declarados, escáneres y fuentes sin texto analizable. El alta/baja de temas y cuentas es una
  decisión humana y queda en la bitácora.
- **Retención**: `events`/`findings` 90 días; clusters se reemplazan en cada ciclo; bitácora
  permanente; suscripciones con doble opt-in y baja en cualquier momento.
- **Salvaguardas**: no atribuye sin evidencia, «UNKNOWN» es válido y hay contacto para
  rectificaciones. Visible en el dashboard (Transparencia → *Gobernanza de datos y salvaguardas*).


## Bus factor, backup offsite y continuidad

**Bus factor 1** (desarrollador único activo). Para mitigar:

- **Backup offsite semanal** (`scripts/backup_offsite.sh`, cron domingo
  03:00): copia `config.yaml` y `data/bitacora.db` a `backups/offsite/`
  (rotación 4 copias). Cualquier colaborador puede restaurar el radar
  desde estos ficheros sin necesidad de acceso al server original.
- **Configuración documentada**: `config.yaml` y `docs/FUENTES.md`
  describen cada feed, su `bias`, `reliability` e `idioma`. Añadir
  una fuente requiere documentar estos campos.
- **Bitácora pública**: toda decisión de estado queda registrada en
  `data/bitacora.db` (fecha, motivo, responsable).
- **Orquestación**: `scripts/cron_every_6h.sh` es el único script
  orquestador del pipeline; su contenido es auto-documentado con
  comentarios por paso.

## Seguridad del despliegue

Cabeceras HTTP servidas por nginx (dominio fimi.viajeinteligencia.com, detrás de Cloudflare):

- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HSTS, sin preload)
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Content-Security-Policy`: `default-src 'self'; script-src 'self' 'unsafe-inline'; ...`

La CSP usa `'unsafe-inline'` porque el dashboard es **un único HTML autocontenido**
(CSS+JS inline generado por `gen_fimi_html.py` cada 6 h). No es una vulnerabilidad
explotable: el inline lo genera el pipeline propio, no input de usuario. El código inline
fuera de la CSP (extraer CSS/JS a ficheros externos) permitiría subir la nota de
[Mozilla Observatory](https://developer.mozilla.org/en-US/observatory/analyze?host=fimi.viajeinteligencia.com)
de B+ a A+, pero se ha decidido mantener la arquitectura actual.

Estado real (escaneo Mozilla Observatory desde navegador, 2026-09-07): **B+ 80/100,
11/12 tests**; único fallo = CSP (−20 por `unsafe-inline`). La nota mide el despliegue
técnico, no la calidad del modelo FIMI.

Otros controles: rate-limit `limit_req` en `/api/*` (429), `.env` y `data/radar.db`
con permisos 600, validación de `cluster_label` en `/api/export` (solo
`[a-z0-9_]+(_cluster_[0-9]{3})?`, previene path traversal/SQLi), endpoints de admin con
`x-admin-secret`.

## Auto-auditoría y salud del sistema

El sistema se auto-chequea frente a fallos silenciosos (config válida + 0 errores pero un
tema que no ve su ruido real — el patrón que dejó ciego a `oriente_medio` hasta 2026-09-09).
Tres capas, todas avisando por Telegram al administrador solo ante cambios (sin spam):

- **`salud_keywords.py`** (card *Salud de keywords*): compara el material del corpus que
  matchea las keywords de cada tema contra lo realmente etiquetado. Alerta si hay un hueco
  grande (≥50 eventos del ámbito sin etiquetar) o si >50 % de las keywords no matchean nada
  (keywords de registro metodológico, p. ej. "desinformación guerra Gaza", que los titulares
  reales no usan). Cron paso 9.
- **`temas_cli.py alta --verifica`**: al crear un tema, simula la cobertura de las keywords
  propuestas contra el corpus y avisa antes de dar de alta si matchean poco.
- **`check_sistema.py`** (card *Salud del sistema*): check médico integral — frescura de
  captura (`MAX(events.timestamp)` vs 7,5 h), snapshot por tema activo
  (`MAX(clusters.created_at)` vs 7 h), integridad BD (event_temas huérfanos) y coherencia
  config (keywords con tema inexistente). Alerta cuando el nivel global empeora
  (ok → atención → incidencia). Cron paso 10. Fue este check el que detectó el
  congelamiento de `frontera_sur` por OOM (2026-09-11): la captura estaba fresca pero el
  tema llevaba 30 h sin regenerar su snapshot.

## Licencia

Este proyecto se publica bajo la **GNU Affero General Public License v3.0 (AGPL-3.0)**
— ver [`LICENSE`](LICENSE). Es una licencia copyleft de red: si despliegas una versión
modificada de este software como servicio accesible por red, debes ofrecer el código
fuente completo de tu versión bajo la misma licencia. El texto completo está en
<https://www.gnu.org/licenses/agpl-3.0.html>.

El dashboard público (`fimi.viajeinteligencia.com`) lo hace visible: el chip
**"Open Source"** de su barra de marca enlaza directamente a este fichero
[`LICENSE`](LICENSE), de modo que la evidencia de la licencia FOSS "in its
entirety" es accesible desde la propia interfaz.


