# European Hybrid & FIMI Radar

Sistema OSINT **agnóstico al actor** para detectar comportamientos anómalos, coordinación,
amplificación artificial, campañas e infraestructura relacionada con posibles operaciones
de manipulación o interferencia (FIMI — Foreign Information Manipulation and Interference).

> **Regla de oro:** OBSERVACIÓN → ANOMALÍA → COORDINACIÓN → CLUSTER → CAMPAÑA →
> INFRAESTRUCTURA → HIPÓTESIS DE ACTOR → ATRIBUCIÓN CON NIVEL DE CONFIANZA.
> Nunca al revés (no partir de un actor sospechoso).

## Estado en producción

El radar opera en vivo en **`fimi.viajeinteligencia.com`** con **4 temas monitorizados**:

| Tema | Estado |
|---|---|
| Frontera Sur (España-Marruecos) | Producción |
| Geopolítica UE-Marruecos | Producción |
| Política nacional | Producción |
| Política y desinformación EEUU | Piloto (en calibración) |

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

- **Telegram**: bot dedicado (long-poll, `detection/radar_bot.py`) con `/radar`, `/mis` y
  `/baja`. El envío de avisos lo hace `detection/notify_subs_telegram.py` (añadido al cron
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
