# European Hybrid & FIMI Radar — WAYAHEAD / ROADMAP

## Estado actual (verificado 31/08/2026)

- **MVP completo en local** (`~/hybrid-fimi-radar`), repo `mcasrom/hybrid-fimi-radar`.
- **DEPLOY A HETZNER (24/7)**: captura + análisis corren en `178.105.80.193`
  (`/home/deploy/hybrid-fimi-radar`), cron `30 */6 * * *` cada 6h.
  Corrección del error de concepto: el laptop no está 24h, el server sí.
  Primera captura en server: 331 eventos reales.
- **Validación sintética (criterio de éxito binario cumplido):**
  - ARI **1.000** (separación perfecta de clusters coordinados)
  - **0 falsos positivos** (900 cuentas orgánicas no disparan)
  - B (campaña doméstica), C (extranjera), F (atribución desconocida) → **100%**
  - D (falsa alarma) NO dispara · E (evento viral orgánico) NO se marca como campaña
- **Pipeline 7 etapas**: ingest → features → anomalías → coordinación → clustering → scoring → atribución.
- **Modelo SQLite completo**: sources, events, narratives, clusters, indicators, assessments, evidence.
- **Atribución separada** con confianza (NO/LOW/MEDIUM/HIGH) + taxonomía neutra + hipótesis H1-H6.
- **Captura real funcionando**: Bluesky (auth operador) + Telegram + Google News + RSS oficiales
  (El País, BBC, Al Jazeera; Interior/ACNUR/Frontex pendientes de verificar feeds).
- **Cron 6h** instalado: `20 */6 * * *` (captura + análisis).
- **Dashboard** Streamlit: http://127.0.0.1:8502

## Límites conocidos (no promesas)

1. **Necesita historia acumulada**: con una captura única (453 eventos, 8 fuentes) hay 0 clusters
   — correcto y esperado. La coordinación real emerge con días de acumulación del cron 6h.
2. **X/Twitter no accesible** (API de pago): la red donde más coordinación ocurre queda fuera.
3. **Interior/ACNUR/Frontex**: feeds configurados pero no trajeron eventos en la primera captura;
   verificar si las URLs son válidas.
4. **Atribución aún heurística**: la separación H2 (doméstica) vs H3 (extranjera) depende de la
   señal de infraestructura; requiere más calibración con casos reales.
5. **`events` en BD**: el schema centralizado no guarda hashtags/mentions/action (se deriva el
   autor de source). Si se quiere detección por cuenta real, hay que enriquecer la captura.

---

## SPRINT 2026-09-01 — Próximo sprint

### Objetivo
Pasar de MVP validado en sintético a **radar funcional con datos reales acumulados**,
y preparar el despliegue en Hetzner.

### P0 — Dejar que el cron acumule y evaluar señal real
| # | Tarea | Aceptación |
|---|---|---|
| S1 | Dejar el cron 6h acumulando ≥ 5-7 días | data/radar.db crece con historia real |
| S2 | Revisar informe tras la acumulación: ¿emergen clusters de coordinación real? | Documentar clusters reales con evidencia (textos, URLs, fuentes) |
| S3 | Si no emerge señal real con estas fuentes, documentarlo como resultado válido (el prompt lo permite) | Conclusión honesta en informe |

### P1 — Enriquecer fuentes y datos
| # | Tarea | Aceptación |
|---|---|---|
| S4 | Verificar/arreglar feeds RSS oficiales (Interior, ACNUR, Frontex) | Traen eventos en la captura |
| S5 | Enriquecer captura: guardar hashtags/mentions/author real por cuenta (no solo source) | Detección por cuenta real viable |
| S6 | Añadir fuentes específicas del caso España-Marruecos-Ceuta-Melilla-Canarias (prensa local, ACNUR país, Frontex región) | Cobertura del primer caso de uso |

### P2 — Afinar atribución y scoring
| # | Tarea | Aceptación |
|---|---|---|
| S7 | Calibrar H2 vs H3 con casos reales (usar infraestructura + transversalidad, no solo score de coordinación) | Atribución no dice FOREIGN sin infraestructura compartida confirmada |
| S8 | Validar bandas de score (NORMAL→CRITICAL) contra clusters reales | Bandas coherentes con la evidencia |

### P3 — Despliegue Hetzner
| # | Tarea | Aceptación |
|---|---|---|
| S9 | Clonar repo a Hetzner (solo cuando haya señal real validada) | MVP corriendo en server |
| S10 | Migrar a PostgreSQL cuando el volumen lo justifique | Esquema exportado desde SQLite |
| S11 | Publicar dashboard tras auth/nginx | Acceso seguro |

### P4 — Auditoría y ética
| # | Tarea | Aceptación |
|---|---|---|
| S12 | Tests unitarios: FP/FN en escenarios A-F (cada escenario con métrica) | Cobertura de los 6 escenarios |
| S13 | Auditoría: cada alerta reproducible (raw → features → params → score) | Evidencia persistida en BD |

### Criterio de éxito del sprint
- El cron acumula ≥ 5 días de datos reales sin errores.
- Se documenta honestamente: clusters reales emergentes O "no hay señal con estas fuentes".
- La atribución no dice FOREIGN sin infraestructura compartida confirmada.
- Tests de FP/FN pasan en los 6 escenarios sintéticos.
- Despliegue a Hetzner SOLO si hay señal real que lo justifique.

## AVANCE 31/08 (mismo día del sprint)
- DEPLOY Hetzner 24/7: captura + análisis + dashboard en fimi.viajeinteligencia.com.
- 19 fuentes (Magreb en francés añadidas). Corrección: credenciales Bluesky en ruta del server.
- Nuevas capacidades implementadas y validadas:
  - Detección de narrativas amplificadas (mismo titular en ≥3 fuentes).
  - Persistencia de hallazgos (tabla findings) + informe diario.
  - Alerta de narrativas sostenidas (≥3 días distintos = campaña sostenida).
  - Dashboard con KPIs, gráfico de intensidad, historial y texto completo.
- Análisis de accesos del ecosistema: viabilidad confirmada (4.235 humanos/día).
- PENDIENTE del sprint (no bloquea): revisar clusters tras ≥5 días de acumulación (S1-S3),
  calibrar H2/H3 (S7), despliegue PostgreSQL solo si hay señal real (S10).

## AVANCE 31/08 (mismo día del sprint)
- DEPLOY Hetzner 24/7: captura + análisis + dashboard en fimi.viajeinteligencia.com.
- 19 fuentes (Magreb en francés añadidas). Credenciales Bluesky en ruta del server.
- Nuevas capacidades: narrativas amplificadas, persistencia de hallazgos (findings),
  informe diario, alerta de narrativas sostenidas (>=3 dias), dashboard con historial.
- Análisis de accesos ecosistema: viabilidad confirmada (4.235 humanos/dia).
- PENDIENTE: clusters tras >=5 dias de acumulacion, calibrar H2/H3, PostgreSQL si hay señal.

---

## SPRINT 2026-09-04 — Estado real DESPLEGADO y suscripciones

El radar ya NO es un MVP Streamlit local: es un dashboard HTML estático multi-tema servido por
nginx (`/var/www/fimi/index.html` generado por `detection/gen_fimi_html.py`) con cron 6h.

### Estado real en producción (fimi.viajeinteligencia.com)
- **Catálogo multi-tema (config.yaml)**: `frontera_sur` (producción),
  `geopolitica_ue_marruecos` (producción), `politica_nacional` (PILOTO, con disclaimer).
  Nótese: `elecciones_2026` NO existe en el catálogo y no debe mencionarse.
- **Vista resumen de diales SVG** (sin librería) por tema: estado Subiendo/Estable/Bajando/
  En recopilación + frase de contexto. Detalle técnico en pantalla 2 vía "Ver detalle".
- Tendencia por tema = hallazgos/clusters HOY vs hace 48h (columna `findings.tema_id`).
- Iteraciones del dashboard: tarjeta interpretable (componentes 0-100), narrativas a ancho
  completo, gráfico de barras clicable WATCH/ANOMALOUS, historial agrupado por tipo
  (`<details>` colapsado), y contexto real por cluster ("De qué habla este cluster") en
  barras y tarjetas.
- **Footer**: enlace a GitHub del repo + versión desplegada (git describe).

### Suscripciones (canal Telegram hecho / email pendiente)
Esquema centralizado en una única tabla `suscripciones`
(`detection/schema_suscripciones.py`): id hash, canal, destino, temas JSON, frecuencia,
ultimo_estado, fecha_alta, confirmado. Base para telegram/email/futuros.

- **Telegram (implementado, falta token para activar)**:
  - `detection/radar_bot.py`: bot dedicado long-poll con `/radar` (teclado inline multi-
    selección de temas), `/mis`, `/baja`. Token desde `FIMI_TELEGRAM_BOT_TOKEN` (env/`.env`).
  - `detection/notify_subs_telegram.py`: se añade al cron 6h; compara dial actual vs
    `ultimo_estado` de cada suscrito y SOLO envía si cambió (on_change, sin spam).
    politica_nacional añade "(piloto, en calibración)".
  - `detection/radar_trend.py`: fuente de verdad del estado del dial (mismo criterio que
    el dashboard), compartida por bot y notificador.
- **Email (pendiente de activar)**: backend Flask/FastAPI + **Resend** — dominio
  viajeinteligencia.com ya verificado (`newsletter@viajeinteligencia.com`, sistema
  `/home/deploy/newsletter/`). Doble opt-in, frecuencia semanal, enlace de baja en cada
  email. Actualizar el footer "sin cuentas" al activarlo (pide un dato = email).

### PENDIENTE / PRÓXIMO
1. Poner el token de `@sieg_politica_bot` en `/home/deploy/hybrid-fimi-radar/.env`
   (`FIMI_TELEGRAM_BOT_TOKEN=...`) y arrancar el bot como PM2 (`radar-fimi-bot`).
2. Activar la parte email (Flask/FastAPI + Resend + doble opt-in + footer).
3. Compartir agregado de los 3 diales (X/Bluesky) desde la vista de diales.
4. Verificar que `geopolitica_ue_marruecos` / `politica_nacional` generan clusters tras
   un ciclo de cron (captura ya etiqueta eventos: 299 y 293 respectivamente).
5. Verificar que el historial de clusters nuevos muestre el contexto persistido
   (los históricos 001-021 no lo recuperan: ids inestables entre ciclos).

### Notas técnicas
- Los ids de cluster NO son estables entre ciclos (DELETE+re-INSERT con nuevos lastrowid),
  por eso el contexto de un cluster se persiste EN el finding al detectarlo
  (`topic_dominant` → detalle `score X/100, N cuentas | <titular>`).
- `.env` y `reports/` están en `.gitignore` (el token nunca va al repo).
- Errores de consola de Cloudflare Insights (beacon CORS/sha512) son ruido del navegador,
  no del código.
