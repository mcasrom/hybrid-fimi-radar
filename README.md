# European Hybrid & FIMI Radar

Sistema OSINT **agnóstico al actor** para detectar comportamientos anómalos, coordinación,
amplificación artificial, campañas e infraestructura relacionada con posibles operaciones
de manipulación o interferencia (FIMI — Foreign Information Manipulation and Interference).

> **Regla de oro:** OBSERVACIÓN → ANOMALÍA → COORDINACIÓN → CLUSTER → CAMPAÑA →
> INFRAESTRUCTURA → HIPÓTESIS DE ACTOR → ATRIBUCIÓN CON NIVEL DE CONFIANZA.
> Nunca al revés (no partir de un actor sospechoso).

## Validación (test sintético FIMI)

Generador sintético con 6 escenarios (tests/generate_synthetic.py):
A orgánico · B campaña doméstica · C campaña extranjera · D falsa alarma ·
E evento real viral · F atribución desconocida.

Resultado sobre el dataset sintético (5498 eventos, 1355 cuentas):

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

# 2. Ejecutar el pipeline completo (detección + scoring + atribución + SQLite)
python detection/run_fimi.py --input data/raw/events.csv --db data/radar.db

# 3. Dashboard
streamlit run app.py
```

## Arquitectura

```
COLLECTORS → RAW → NORMALIZER → FEATURES → DETECTION → CLUSTERING → SCORING
→ ATTRIBUTION → SQLITE → REPORT → DASHBOARD
```

```
hybrid-fimi-radar/
├── app.py                  # Dashboard Streamlit
├── config.yaml             # Pesos, bandas de score, fuentes (configurables)
├── requirements.txt
├── collectors/             # captura (Bluesky/Telegram/RSS/GoogleNews/Reddit/Mastodon)
├── normalizer/             # ingest + schema SQLite
├── features/               # características temporales/contenido/bot-signals
├── detection/              # anomalías, coordinación, cascadas, scoring, pipeline
├── clustering/             # componentes conexas + evidencia por cluster
├── attribution/            # atribución con confianza + hipótesis H1-H6
├── tests/                  # generador sintético + validación
├── reports/                # informes Markdown
└── docs/
```

## Modelo de datos (SQLite)

`sources` · `events` · `narratives` · `clusters` · `indicators` · `assessments` · `evidence`
(esquema en normalizer/schema.py).

## Suscripciones (Telegram / newsletter)

Esquema centralizado en una única tabla para todos los canales:
`suscripciones (id, canal, destino, temas, frecuencia, ultimo_estado, fecha_alta, confirmado)`.
Crea la tabla con `python detection/schema_suscripciones.py`.

- **Telegram**: bot dedicado (long-poll, `detection/radar_bot.py`) con `/radar`, `/mis` y
  `/baja`. El envío de avisos lo hace `detection/notify_subs_telegram.py` (añadido al cron 6h):
  solo notifica cuando un dial cambia de estado (on_change), comparando contra
  `ultimo_estado` — sin spam.
- **Email (pendiente de activar)**: backend Flask/FastAPI + Resend (dominio
  viajeinteligencia.com ya verificado en `newsletter@viajeinteligencia.com`), doble opt-in,
  frecuencia semanal, enlace de baja en cada correo.
- **Estado del dial**: fuente de verdad compartida en `detection/radar_trend.py` (mismo
  criterio HOY vs hace 48h que los diales de la vista resumen).

El token del bot se lee de `FIMI_TELEGRAM_BOT_TOKEN` (env/`.env`), nunca hardcodeado; `.env`
está en `.gitignore`.

## Atribución (separada del detector)

Taxonomía neutra: UNKNOWN / DOMESTIC / FOREIGN_STATE / FOREIGN_NON_STATE /
TRANSNATIONAL_NETWORK / PROXY / MIXED / UNDETERMINED.

Confianza: NO_ATTRIBUTION / LOW / MEDIUM / HIGH. La ausencia de atribución es
**un resultado válido**. Nunca se usa ideología como indicador de amenaza.

## Hipótesis alternativas (anti sesgo de confirmación)

H1 orgánico viral · H2 campaña doméstica · H3 operación extranjera ·
H4 amplificación mediática · H5 campaña política · H6 desconocido.

## Honestidad metodológica

- El sistema **no busca confirmar** que "Rusia/China/Marruecos/EEUU/izquierda/derecha"
  están detrás de una campaña. Dice lo que observa, lo que es estadísticamente anómalo,
  las evidencias de coordinación y las hipótesis posibles con su nivel de confianza.
- "No existe evidencia suficiente para atribuir a un actor extranjero" es una conclusión válida.
- Sin LLM como componente principal del detector (solo estadística clásica, explicable).
