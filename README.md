# European Hybrid & FIMI Radar

Sistema OSINT **agnóstico al actor** para detectar comportamientos anómalos, coordinación,
amplificación artificial, campañas e infraestructura relacionada con posibles operaciones
de manipulación o interferencia (FIMI — Foreign Information Manipulation and Interference).

> **Regla de oro:** OBSERVACIÓN → ANOMALÍA → COORDINACIÓN → CLUSTER → CAMPAÑA →
> INFRAESTRUCTURA → HIPÓTESIS DE ACTOR → ATRIBUCIÓN CON NIVEL DE CONFIANZA.
> Nunca al revés (no partir de un actor sospechoso).

## Estado en producción

El radar opera en vivo en **`fimi.viajeinteligencia.com`** con **6 temas monitorizados**:

| Tema | Estado |
|---|---|
| Frontera Sur (España-Marruecos) | Producción |
| Geopolítica UE-Marruecos | Producción |
| Política nacional | Producción |
| Política y desinformación EEUU | Piloto (en calibración) |
| Oriente Medio (Israel-Irán-Gaza) | Piloto (en calibración) |
| Sahel (África Occidental) | Piloto (en calibración) |

- **Pipeline**: captura + detección + scoring ejecutados por cron cada 6 h
  (`scripts/cron_every_6h.sh`).
- **Dashboard**: HTML estático generado por `detection/gen_fimi_html.py` y servido por
  nginx, reorganizado en **pestañas sticky** (Radar | Transparencia | GitHub) con un
  **hero de centro de situación** (OBSERVAR → DETECTAR → CONTRASTAR + estado en vivo),
  **barra de ecosistema persistente** (viajeinteligencia.com · Herramientas · Blog
  analisis.pruebapublica.com · pruebapublica.com), un **panel de situación "de un vistazo"**
  (tiles KPI: eventos · fuentes · clusters · en alerta · temas; **distribución de clusters
  por banda**; y una **tira por tema** con color de banda, score, tendencia y nº de
  clusters — aditivo, no sustituye los diales), diales por tema, tarjetas de cluster
  (con "De qué habla", **dominios que amplifican por cluster** — eco de un medio vs red —,
  chips de trayectoria "ecos de 1 pieza"/"coordinación sostenida", export CSV/JSON y
  **borde de color por banda** (rojo CRITICAL · naranja HIGH · ámbar ANOMALOUS · cian
  WATCH) para que la gravedad se perciba a contraluz de la página),
  narrativas, historial, resumen por tema, salud de fuentes y bitácora.
- **Divulgación progresiva (detalle de un tema)**: solo se expanden los **6 clusters de
  mayor score**; el resto (incluidos HIGH/CRITICAL fuera del top-6) va a un bloque plegado
  con **gráfico de barras clicable**. Las secciones **globales** (Narrativas + Historial,
  que no pertenecen al tema) y la **leyenda de componentes** quedan en `<details>` cerrados
  por defecto. Evita paneles de decenas de miles de píxeles cuando un tema tiene muchas
  señales en alerta (frontera_sur: ~61.500 px → ~6.000 px).
- **Piloto vs producción visible**: cada tema lleva su estado a la vista — en las
  tarjetas dial y en las pestañas, un badge **`● Producción`** (verde) o
  **`● PILOTO · en calibración`** (naranja, con pulso suave). Los temas en piloto
  muestran además la frase *"piloto en calibración — lectura con cautela"* en una caja
  naranja destacada y un aviso de riesgo de sesgo en su panel. La animación respeta
  `prefers-reduced-motion`.
- **Rendimiento y robustez**: `frontera_sur` es el tema por defecto de los RSS, así que
  procesa el corpus completo (~20.000 eventos, ~3.700 cuentas). Los centroides TF-IDF de
  la coordinación se calculan **en sparse** (`scipy.sparse`) para no agotar la RAM: un
  `np.vstack` denso (cuentas × vocabulario de bigramas) provocaba **OOM** en el server de
  3,7 GB. Run de frontera_sur: ~375 s, pico ~2,7 GB. **Palancas de memoria** ya
  configurables en `config.yaml → coordination`: `window_days` (ventana del grafo, def. 90)
  y `tfidf_max_features` (tope de vocabulario, def. 200.000). Bajarlas permite añadir
  muchas más fuentes sin volver a OOM.
- **Modelo transparente**: la pestaña *Transparencia* expone los pesos del scoring, las
  bandas y la calibración por tema; el dashboard nunca atribuye a un actor sin respaldo.
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

**ARI = 1.000** (separación perfecta de los clusters coordinados), **precisión 100%**,
**0 falsos positivos**.

## Validación externa (EUvsDisinfo)

Cruza la vista activa del radar con el dataset de campañas documentadas de EUvsDisinfo
(`data/euvsdisinfo_base.csv`, Zenodo `10514307`, 18.249 casos / 10.682 de desinformación /
1.311 dominios documentados; se auto-descarga a `data/`, gitignored). Uso:
`tests/validacion_externa.py --json`.

Resultados reales sobre la vista activa (90 d, últimos 5 temas):

- **Precision 0.0%**: los 14 clusters con score ≥ 60 no amplifican ningún dominio
  documentado (amplifican prensa mainstream: eldiario.es, elpais.com, publico.es). No es un
  falso positivo: significa que las señales altas actuales se basan en eco mainstream no
  documentado.
- **Recall 0.0%**: la única fuente del catálogo con dominio documentado (RT en Español,
  `actualidad.rt.com`, 152 eventos capturados) no produce ninguna narrativa ni cluster.

**Interpretación (según el docstring del script):** el recall 0 es un resultado correcto,
no un fallo — los feeds RSS no participan en el grafo de coordinación (por diseño, solo
redes sociales) y los titulares de RT no se replican en ≥ 3 fuentes del catálogo; un radar
de coordinación no debe señalar RT solo por ser RT, sino cuando su narrativa se propaga.
Además, EUvsDisinfo es histórico (2015-2023, foco Ucrania/Rusia), no cubre los temas activos
del radar (Ceuta/Marruecos/España/EEUU/Oriente Medio), por lo que el benchmark valida la
**mecánica** del cruce, no la ausencia de campañas. La evidencia real de que el detector
funciona está en la validación sintética (ARI 1.000) + este cruce de dominios.

## CTA cruzado con el blog (analisis.pruebapublica.com)

Las tarjetas de los temas Frontera Sur, Geopolítica UE-Marruecos, Política nacional y
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
│   ├── temas_emergentes.py # volumen fuera de catálogo (posible tema nuevo)
│   ├── resumen_tema.py     # síntesis por tema (sin IA)
│   ├── health_fuentes.py   # salud y fiabilidad de fuentes (bias/reliability/corroboration)
│   ├── narrativas_alineadas.py  # cluster-of-clusters cross-tema (TF-IDF + coseno)
│   ├── whois_signal.py     # señal de dominio (RDAP) para clusters de alta banda
│   ├── export_evidencia.py # export CSV/JSON de la evidencia de un cluster
│   ├── bitacora.py         # bitácora de temas (inicio/cambio/cierre/sugerencia)
│   ├── check_cierre.py     # candidatura a cierre (solo sugiere, no decide)
│   ├── check_promocion.py  # validación de piloto→producción (72 h, ciclo BD)
│   ├── check_ingesta.py    # alerta si el cron se salta la captura
│   ├── salud_keywords.py   # ¿captura cada tema su ruido real? (patrón "tema ciego")
│   ├── backfill_tema_contenido.py  # re-etiqueta por contenido tras cambiar keywords
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
└── docs/                   # SCORING.md, ATRIBUCION-LIMITACIONES.md, TRAZABILIDAD.md, FUENTES.md
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

El panel del dueño vive en **`/admin.html`** (estático en `/var/www/fimi/`, `noindex`;
no está en el repo) y se autentica con `x-admin-secret` (`FIMI_ADMIN_SECRET`). Muestra
votos por tema, sugerencias, suscriptores por proyecto y **Gestión de temas**.

La gestión de temas refleja el principio *"el sistema no decide"*: los controles solo se
activan cuando el propio radar ya marcó la señal, y la acción la ejecuta el dueño.

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
Tres capas, todas avisando por Telegram al dueño solo ante cambios (sin spam):

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

