# FIMI Radar — Radar de señales de coordinación y amplificación

## 1. Qué es FIMI Radar

**Radar de señales de coordinación y amplificación:** sistema OSINT que detecta, con
datos públicos, **patrones observables de sincronización, repetición de contenido y
agrupación estructural** de la conversación en redes sociales y prensa sobre un conjunto
de temas (frontera sur y Marruecos, Oriente Medio, elecciones, energía, IA, Sahel,
amenazas híbridas en España, defensa…). Mira **quién empuja el mismo mensaje, a la vez
y de la misma forma**, para señalar patrones potencialmente compatibles con actividades
de influencia o manipulación coordinada (FIMI).

La herramienta **no atribuye actor ni confirma inautenticidad o campaña extranjera por
sí sola**: sus salidas son **señales conductuales** que requieren validación adicional,
análisis contextual y evidencia organizativa. No dictamina "qué es verdad o mentira".
Está pensado para periodistas, investigadores y ciudadanía que quieran comprobar los
datos por sí mismos.

## 2. Qué NO hace

- **No atribuye autoría ni intención.** La atribución es un módulo aparte y conservador:
  por defecto el resultado es `UNKNOWN`. El radar no dice "esto lo hace Rusia/China/
  Marruecos/EEUU/la izquierda/la derecha".
- **No evalúa ideología**: una opinión nunca se trata como amenaza.
- **Describe patrones, no intenciones.** Mide forma (sincronía, enlaces repetidos,
  recurrencia), no el porqué.
- **No señala a personas.** El radar **sí muestra los identificadores públicos** de las
  cuentas que forman un cluster (son la prueba de la coordinación), pero **no perfila a
  nadie**: no infiere datos personales, no evalúa a individuos ni los presenta como
  culpables. Un cluster describe un comportamiento colectivo, no una acusación.
- **No decide.** Avisa y sugiere (promover/cerrar un tema); la decisión es siempre humana.

## 3. Cómo funciona (a nivel conceptual)

Cada 6 h captura publicaciones públicas (Bluesky, Telegram, Reddit, Mastodon, Google News
y RSS), las normaliza y calcula componentes estructurales por **cluster** de cuentas:

- **Sincronización (coordinación):** cuánto coinciden en el tiempo las publicaciones.
- **Anomalía:** cuánto se desvía el comportamiento de esas cuentas del habitual
  (detección de valores atípicos, sin conocer antes a la cuenta).
- **Infraestructura:** enlaces/dominios compartidos entre cuentas.
- **Similitud de contenido** y **amplificación** (señal global del ciclo).

> La **densidad de red** se calcula y se publica como dato, pero **no pondera en el
> score**: es una transformación del mismo eje de coordinación (doble conteo) y se
> retiró el 24/Sep-2026. La usa el módulo de atribución (hipótesis H3).

Con eso calcula una **puntuación 0-100** y una **banda** (NORMAL→CRITICAL), y evalúa
**hipótesis alternativas** (anti sesgo de confirmación):

H1 viralización orgánica · H2 campaña coordinada doméstica *con estructura* ·
**H2b sincronización sin atribución de operador** · H3 operación de influencia extranjera ·
H4 amplificación mediática · H5 sincronía sostenida con contenido diverso (sin estructura) ·
H6 sin evidencia concluyente.

Las hipótesis **no cambian la puntuación**; son una lectura informativa.

## 4. Estado actual

Snapshot del último run (24/Sep/2026, **v0.2**):

- **9 temas activos** (7 en producción + 2 en piloto: `elecciones`, `defensa_espana`).
- **~113.500 eventos** y **824 clusters** (ventana de 90 días).
- **68 feeds RSS** + 2 búsquedas de plataforma, 3 canales de Telegram público, 2 subreddits.
- Dashboard en vivo: https://fimi.viajeinteligencia.com · API v1 read-only: `/api/v1/…`.
- Última release: **v0.2**.

## 5. Limitaciones conocidas

- **Atribución estructural únicamente:** no consulta evidencia organizativa (salvo una
  señal débil de dominio vía RDAP). `UNKNOWN` no significa "no hay campaña", sino que la
  evidencia estructural no basta para atribuir.
- **El score es una señal conductual, no una condena:** una banda HIGH indica
  comportamiento coordinado anómalo, no prueba de orquestación.
- **Cobertura limitada:** X/TikTok/Instagram/Facebook/YouTube/WhatsApp no se observan
  (coste/API o no público); falta análisis multimodal (imagen/vídeo).

Detalle completo en [`docs/ATRIBUCION-LIMITACIONES.md`](docs/ATRIBUCION-LIMITACIONES.md).
El proyecto **documenta y corrige sus propios sesgos**: por ejemplo, el commit `aa5280f`
separó "campaña coordinada doméstica" (ahora exige estructura real) de "sincronización
sin operador" y renombró una hipótesis cuyo nombre no correspondía a lo que medía.

## 6. Arquitectura y cómo correrlo

Pipeline: `COLLECTORS → RAW → NORMALIZER → FEATURES → DETECTION → CLUSTERING → SCORING
→ ATTRIBUTION → SQLITE → REPORT → DASHBOARD`. En producción, un cron lo ejecuta cada 6 h
sobre todos los temas activos de `config.yaml`; el dashboard se publica como HTML estático.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python tests/generate_synthetic.py                 # datos sintéticos de validación
python detection/run_fimi.py --tema frontera_sur   # pipeline de un tema
python detection/gen_fimi_html.py                  # dashboard estático
```

Estructura: `collectors/` (captura), `normalizer/`, `features/`, `detection/` (pipeline,
scoring, atribución, dashboard, salud), `tests/`, `docs/`. Modelo de datos en SQLite
(`data/radar.db`); configuración en `config.yaml` (temas, keywords, pesos, bandas, fuentes).

Documentación en [`docs/`](docs/): `TAXONOMIA.md`, `SCORING.md`, `ATRIBUCION-LIMITACIONES.md`,
`TRAZABILIDAD.md`, `GOBERNANZA.md`, `RUNBOOK.md`, `FUENTES.md`, `EIPD-DPIA.md`. Versión
detallada de este README (histórico): [`docs/README-detallado.md`](docs/README-detallado.md).

## 7. Licencia y contacto

**AGPL-3.0** (copyleft de red): quien lo modifique y lo ofrezca como servicio debe publicar
su código fuente. Ver [`LICENSE`](LICENSE).

- Dudas, correcciones o **derecho de respuesta**: **info-fimi@viajeinteligencia.com**
- Incidencias y código: [GitHub Issues](https://github.com/mcasrom/hybrid-fimi-radar/issues)
- Bot de alertas (Telegram): `@Sieg_politica_bot` (nombre visible: RadarFIMI_bot)
