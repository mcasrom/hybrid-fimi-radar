# Observatorio de señales de coordinación y amplificación (ámbito FIMI)

*[English](README.en.md) · Español*

## 1. Qué es

**Observatorio de señales de coordinación y amplificación:** sistema OSINT que detecta, con
datos públicos, **patrones observables de sincronización, repetición de contenido y
agrupación estructural** de la conversación en redes sociales y prensa sobre un conjunto
de temas (frontera sur y Marruecos, Oriente Medio, elecciones, energía, IA, Sahel,
defensa y amenazas híbridas…). Mira **quién empuja el mismo mensaje, a la vez
y de la misma forma**, para señalar patrones potencialmente compatibles con actividades
de influencia o manipulación coordinada (FIMI). FIMI es el **ámbito** que se observa,
no una detección: el observatorio **no** confirma campañas ni atribuye actores.

La herramienta **no atribuye actor ni confirma inautenticidad o campaña extranjera por
sí sola**: sus salidas son **señales conductuales** que requieren validación adicional,
análisis contextual y evidencia organizativa. No dictamina "qué es verdad o mentira".
Está pensado para periodistas, investigadores y ciudadanía que quieran comprobar los
datos por sí mismos.

## 2. Qué NO hace

- **No es un detector de FIMI.** No demuestra que exista una campaña: produce
  **candidatos para investigación**. Los clusters HIGH/CRITICAL tienen **explicaciones
  alternativas plausibles** —y a menudo más parsimoniosas—: eco de prensa, viralidad
  orgánica, activismo coordinado legítimo, automatización no maliciosa o artefactos del
  grafo. Sostener "FIMI confirmado" exige **evidencia externa independiente**.
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

Cada cluster publica además **`alternative_explanations`**: explicaciones alternativas con
estado (`supported` / `plausible` / `ruled_out`) y la **evidencia** que lo motiva. Distingue,
entre otras, dos situaciones que **no deben confundirse**:

- **`single_source_feed` — «Feed de una sola fuente»**: una **cuenta o un dominio concentran
  casi todo** (p. ej. alguien que publica su propio sitio). No es coordinación entre cuentas
  distintas → **prioridad baja**.
- **`cross_account_synchrony` — «Reproducción coordinada entre cuentas»**: **varias cuentas
  distintas, ninguna dominante, con el mismo contenido**. Este es el patrón que **sí merece
  revisión humana** → **prioridad alta**.

Y también eco de prensa, eco de una sola pieza, viralidad orgánica, sincronización sin operador,
automatización no maliciosa, movilización legítima, artefacto del grafo y *sin explicación
concluyente*. No es una clasificación de "la verdad": es material para la revisión humana,
visible en el dashboard, la API y las exportaciones.

Cada cluster publica además un **rol narrativo** (`narrative_subtype`) que separa *hablar de
FIMI* — `official_response` (respuesta oficial), `incident_report` (reporte de incidente),
`meta_analysis` (análisis) — de *posible narrativa FIMI* (`potential_narrative`,
`coordination_signal`). Ayuda a no leer como "operación" lo que es una noticia que la combate
o la analiza.

Con eso calcula una **puntuación 0-100** y una **banda** (NORMAL→CRITICAL), y evalúa
**hipótesis alternativas** (anti sesgo de confirmación):

H1 viralización orgánica · H2 campaña coordinada doméstica *con estructura* ·
**H2b sincronización sin atribución de operador** · H3 operación de influencia extranjera ·
H4 amplificación mediática · H5 sincronía sostenida con contenido diverso (sin estructura) ·
H6 sin evidencia concluyente.

Las hipótesis **no cambian la puntuación**; son una lectura informativa.

### Auditoría de señales altas (HIGH/CRITICAL)

Para que cada señal alta pueda revisarse **sin afirmar que sea FIMI**, `detection/auditoria_high.py`
genera un registro auditable por cluster con score ≥60: cuentas, eventos, URLs/dominios distintos,
ventana temporal, componentes, k-core, **rol narrativo** y **explicaciones alternativas**, más la
**cadena** que separa la *coordinación observable* (medida) de la *inautenticidad*, la *intención* y
la *dimensión extranjera* (que el radar no puede confirmar por sí solo) y del *FIMI confirmado* (que
requiere evidencia independiente). Ordena la revisión por prioridad humana.

Es de **solo lectura y ligero**: audita únicamente los clusters ≥ umbral y sus eventos, con límites
configurables (`auditoria` en `config.yaml`: máx. de clusters, eventos y longitud de texto, timeout,
semilla). No usa red, LLMs ni dependencias pesadas.

```bash
python detection/auditoria_high.py --formato csv --out auditoria_high.csv
python detection/auditoria_high.py --tema <tema> --limite 50
python detection/auditoria_high.py --formato blind --muestra 40 --seed 7 --out ciego.csv
```

En `--formato blind` el muestreo se aplica **siempre** (con `--muestra`/`--seed`; si omites
`--muestra`, se usan **40 filas** por defecto, `auditoria.blind_default_muestra`). El CSV ciego
**no** incluye rol narrativo, explicación principal, prioridad, hipótesis ni atribución: solo
evidencia bruta y componentes (cuentas, eventos, URLs/dominios, ventana, k-core, textos y URLs
de evidencia) más las columnas `label_*` **vacías** para la anotación humana.

## 4. Estado actual

Snapshot del último run (29/Sep/2026, **v0.2**; las cifras crecen cada ciclo — el dashboard
muestra el valor vivo):

- **8 temas activos** (6 en producción + 2 en piloto: `elecciones`, `defensa_espana`).
  `espana_amenazas_hibridas` se fusionó en `defensa_espana` el 27/Sep (renombrado «España — defensa y amenazas híbridas»).
- **~146.000 eventos** y **1.052 clusters** (ventana de 90 días), repartidos en
  589 WATCH · 363 ANOMALOUS · 100 HIGH · 0 CRITICAL.
- **~72 feeds RSS** + 2 búsquedas de plataforma, 8 canales de Telegram público, 2 subreddits.
- Dashboard en vivo: https://fimi.viajeinteligencia.com · API v1 read-only: `/api/v1/…`.
- Última release: **v0.2**.

## 5. Limitaciones conocidas

- **Atribución estructural únicamente:** no consulta evidencia organizativa (salvo una
  señal débil de dominio vía RDAP). `UNKNOWN` no significa "no hay campaña", sino que la
  evidencia estructural no basta para atribuir.
- **El score es una señal conductual, no una condena:** una banda HIGH indica
  comportamiento coordinado anómalo, no prueba de orquestación.
- **Validación honesta y experimental.** La separación de grupos se mide con datos
  **sintéticos** (ARI) y con capas curada/externa; **ninguna demuestra detección de FIMI
  real**. La validación humana **ciega** —con etiquetas separadas de *coordinación
  observable*, *comportamiento inauténtico/manipulativo* y *FIMI con evidencia externa
  independiente*— está **preparada** (`auditoria_high --formato blind`) pero **no
  ejecutada** todavía.
- **Cobertura limitada:** X/TikTok/Instagram/Facebook/YouTube/WhatsApp no se observan
  (coste/API o no público); falta análisis multimodal (imagen/vídeo).
- **Qué cuenta hoy como "coordinación" — y qué no.** Medido sobre producción
  (29/Sep/2026 10:14 UTC, 1052 clusters, 20.016 eventos miembro):
  - El grafo de coordinación **solo contiene cuentas sociales por diseño** (los medios se
    capturan, pero no son miembros de ningún cluster). Que HIGH sea Bluesky es una
    **tautología del corpus**, no un sesgo medido: las cuentas que clusterizan tienen
    27.624 eventos y **ninguno de prensa**. No debe citarse como hallazgo.
  - En **27 de los 100 HIGH** una sola cuenta aporta ≥55 % de los eventos del cluster, y
    esas cuentas son en su mayoría **agregadores/feeds** (`greasydump`, `news-flows-nl`,
    `topnewsde`, `cnn-news`, `efe.com`, `worldnewsbriefly`, `afrique.rfi.fr`…). El **23 %**
    tiene 3 cuentas o menos (mediana 6, media 13).
  - Repartidos por su **primera explicación `supported`**: 37 `single_source_feed`,
    25 `sustained_amplification`, 20 `unresolved`, 10 `syndicated_wire`, 4
    `synchronized_without_operator`, 3 `automated_non_malicious` y **1 solo**
    `cross_account_synchrony`. Es decir: **de 100 alertas HIGH, 1 cumple la definición
    propia de ráfaga coordinada entre cuentas distintas.**
  - Causa: `band_gate` comprueba el **número** de cuentas, no su **peso relativo**, así que
    un feed con 3 bridged-cuentas satisface el mínimo. Gate B medido (exigir que ninguna
    cuenta domine y excluir sindicación): HIGH **100 → 63**, y el único
    `cross_account_synchrony` se conserva. **No aplicado — decisión del dueño.**
  Medición completa y reproducible: [`docs/composicion-bandas-20260929.md`](docs/composicion-bandas-20260929.md).
- **Qué mide el grafo, exactamente.** Reejecutando `build_edges()` sobre producción
  (29/Sep/2026): las aristas son **la misma URL republicada** (dominante) y **textos casi
  idénticos**, con mediana de 0,6-6 h entre las dos cuentas (72-94 % dentro de 24 h). La señal
  que debería distinguir una campaña de una noticia —ráfaga de publicación, `tight_timing`— es
  **casi nula: 4, 11 y 0 aristas** en tres temas (de 937, 2.387 y 1.363). Y la estructura es
  una **cadena de enlaces débiles** (mediana: 1 arista por cluster): el 96 % de WATCH y el 23 %
  de HIGH no tienen ningún nodo de grado ≥3, es decir ninguna cuenta conectada con dos o más
  cuentas del cluster. Por tanto el sistema mide **amplificación simultánea de una misma pieza**,
  que es un hecho verificable; **la diferencia entre noticia y campaña no está implementada**.
  Detalle: [`docs/grafo-coordinacion-20260929.md`](docs/grafo-coordinacion-20260929.md).
- **Un hueco de calibración ya corregido.** Los cortes de banda son enteros y los scores
  decimales, así que un score como 59,96 no caía en ninguna banda y acababa degradado a
  NORMAL en silencio (commit `d52d77c`; 19 clusters afectados, 14 de ellos con score
  59,2–59,96 que en realidad eran ANOMALOUS). No era un error de pesos, sino de asignación de
  banda: `band_for()` ahora toma la última banda cuyo límite inferior sea ≤ score.

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
python detection/run_fimi.py --input data/radar.db --tema frontera_sur   # pipeline de un tema
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
