# Radar FIMI — one-pager

**Un radar abierto de coordinación informativa: mide comportamiento, no autoría.**

`fimi.viajeinteligencia.com` · código: `github.com/mcasrom/hybrid-fimi-radar` (AGPL-3.0)

---

## Qué es

Una herramienta **OSINT, self-hosted y open source** que observa **contenido público**
(RSS de medios, Telegram público, Reddit, Bluesky, Mastodon, Google News) y detecta
**señales de coordinación**: cuentas que publican el mismo contenido en ventanas
similares, amplificación inauténtica, infraestructura compartida y anomalías de red.

Monitoriza **8 temas** en producción y piloto (frontera sur, política nacional, EEUU,
Oriente Medio, Sahel, energía, elecciones, inteligencia artificial) con ~**62.500
eventos** y ~**758 clusters** en el último ciclo.

## Qué hace distinto

- **Señal, no atribución**: puntúa 0-100 (NORMAL→CRITICAL) la **coordinación observada**.
  **No** afirma quién está detrás; **UNKNOWN es un resultado válido**.
- **Anti sesgo de confirmación**: 6 hipótesis alternativas por cluster y atribución
  conservadora (solo actor externo con infraestructura compartida).
- **Transparencia total**: scoring documentado, pesos por tema, bitácora de decisiones,
  y se publican **también los resultados negativos**.
- **Validación honesta** en 3 capas (ver abajo).

## Validación (3 capas, se recalcula sola)

| Capa | Método | Resultado |
|---|---|---|
| **Mecánica** | Sintética (ARI) | **1.000** (gate de CI) |
| **Orden** | Curada (ground truth etiquetado a mano) | precisión **sube con la banda**; WATCH = ruido |
| **Externa** | EUvsDisinfo (dominios documentados) | precision **~8%**, recall 0% (explicado por diseño) |

> Los ceros y los valores bajos se publican tal cual: **no es marketing**.

## Cómo se usa

- **Dashboard** (`fimi.viajeinteligencia.com`): centro de situación por tema.
- **API pública v1** (read-only, JSON + OpenAPI): `/api/v1/temas`, `/api/v1/tema/<slug>`…
- **Newsletter semanal** (lunes) por tema · **bot de Telegram** (alertas on_change).
- **Blog** (`analisis.pruebapublica.com`) con análisis cruzado.

## Límites (declarados)

- **Ceguera de plataformas**: sin TikTok, X, Instagram ni WhatsApp (sin acceso público).
- La **ausencia de señal no implica ausencia de campaña**.
- Los identificadores de cluster **no son estables** entre ciclos (cada respuesta es un
  *snapshot*).
- **Bus factor 1** (mitigado con runbook y documentación).

## Para quién

Periodistas y fact-checkers · investigadores OSINT · academia · instituciones
(EDMO/EU DisinfoLab) · cualquier persona interesada en cómo se coordina la información.

## Encaje y contacto

- **Open source** (AGPL-3.0), **sin rastreo**, datos solo de contenido **público**
  (ver `docs/EIPD-DPIA.md`).
- Contacto: **info-fimi@viajeinteligencia.com**

*Documentación completa: `docs/` (SCORING, TAXONOMIA, FUENTES, GOBERNANZA, RUNBOOK,
ATRIBUCION-LIMITACIONES, TRAZABILIDAD, EIPD-DPIA).*
