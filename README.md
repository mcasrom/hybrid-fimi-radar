# European Hybrid & FIMI Radar

Sistema OSINT **agnóstico al actor** para detectar comportamientos anómalos, coordinación,
amplificación artificial, campañas e infraestructura relacionada con posibles operaciones
de manipulación o interferencia (FIMI — Foreign Information Manipulation and Interference).

> **Regla de oro:** OBSERVACIÓN → ANOMALÍA → COORDINACIÓN → CLUSTER → CAMPAÑA →
> INFRAESTRUCTURA → HIPÓTESIS DE ACTOR → ATRIBUCIÓN CON NIVEL DE CONFIANZA.
> Nunca al revés (no partir de un actor sospechoso).

## Estado en producción

El radar opera en vivo en **`fimi.viajeinteligencia.com`** con **5 temas monitorizados**:

| Tema | Estado |
|---|---|
| Frontera Sur (España-Marruecos) | Producción |
| Geopolítica UE-Marruecos | Producción |
| Política nacional | Producción |
| Política y desinformación EEUU | Piloto (en calibración) |
| Oriente Medio (Israel-Irán-Gaza) | Piloto (en calibración) |

- **Pipeline**: captura + detección + scoring ejecutados por cron cada 6 h
  (`scripts/cron_every_6h.sh`).
- **Dashboard**: HTML estático generado por `detection/gen_fimi_html.py` y servido por
  nginx, reorganizado en **pestañas sticky** (Radar | Transparencia | GitHub) con diales
  por tema, tarjetas de cluster, narrativas, historial, resumen por tema, salud de fuentes
  y bitácora.
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
lo registra en la bitácora.

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
  viajeinteligencia.com verificado en `newsletter@viajeinteligencia.com`), doble opt-in,
  frecuencia semanal y enlace de baja; digest en `detection/email_digest.py`.
- **Estado del dial**: fuente de verdad compartida en `detection/radar_trend.py` (mismo
  criterio HOY vs hace 48h que los diales de la vista resumen).

El token del bot se lee de `FIMI_TELEGRAM_BOT_TOKEN` (env/`.env`), nunca hardcodeado; `.env`
está en `.gitignore`. Los endpoints `/api/*` están protegidos con rate-limit y los de admin
requieren `x-admin-secret`.

## Export de evidencia por cluster

Para auditoría OSINT, `detection/export_evidencia.py` permite descargar los textos, fuentes
y URLs de un cluster en CSV o JSON (`--cluster <label> --fmt csv|json`), o en el dashboard
(los links "Exportar evidencia" de cada tarjeta). Recurso público: los datos ya eran
visibles en las tarjetas; el export solo los facilita.

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
