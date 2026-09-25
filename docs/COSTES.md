# Costes del Radar FIMI — desglose

Transparencia de costes del **Radar FIMI** (orientativo, 2026). El proyecto se sostiene
con donaciones ([Ko-fi](https://ko-fi.com/m_castillo)) y, si se conceden, con financiación
de software libre (NLnet). **No vende ni cede datos.** Esta página es el desglose completo
al que apunta `apoyo.html`.

Cifras orientativas; pueden variar por uso y por proveedor. Los cambios relevantes se
anotan al final.

## Infraestructura base — objetivo: cubrirla

| Concepto | Coste | Para qué |
|---|---|---|
| **Servidor** (Hetzner) | **~20 €/mes** (~240 €/año) | Funcionamiento 24/7: captura de fuentes cada 6 h, dashboard estático y API pública. |
| **Dominio** | **~20 €/año** | `fimi.viajeinteligencia.com`. |
| **Base total** | **~260 €/año** | — |

## Variables — según uso y recaudación

| Concepto | Coste | Para qué |
|---|---|---|
| **APIs de IA de apoyo** | variable | Traducción de fuentes y **asistencia** al análisis y al código. **Nunca** para «detectar» ni atribuir. |
| **APIs de datos** (p. ej. X) | variable | Ampliar **cobertura** de plataformas hoy fuera del radar. |
| **APIs de traducción** | variable | Idiomas hoy no cubiertos. |

## Quién mantiene esto

El Radar FIMI lo desarrolla y mantiene **una sola persona, en su tiempo libre** — no es un
proyecto financiado ni el producto de una empresa. El mantenimiento real (auditar el motor
de detección, corregir sesgos cuando aparecen, revisar clusters, responder issues, escribir
documentación) ocupa habitualmente **varias horas a la semana**, sin coste que se facture a
nadie.

Las donaciones **no cubren ese tiempo** — solo ayudan a que la infraestructura (servidor,
dominio, APIs) siga en pie mientras ese trabajo se sigue haciendo gratis. Un ejemplo reciente
de en qué se traduce ese tiempo: en septiembre de 2026 se **auditó el propio motor de
clasificación** contra un análisis externo, se encontraron **dos sesgos reales** en cómo se
etiquetaban ciertos patrones de coordinación, y se corrigieron en producción en **48 horas**
— todo documentado públicamente en el [repositorio](https://github.com/mcasrom/hybrid-fimi-radar)
(`docs/ATRIBUCION-LIMITACIONES.md`, `docs/TRAZABILIDAD.md`).

Ese trabajo de auditoría y corrección **no aparece en ninguna tabla de costes** porque no
tiene un precio fijado — pero es, probablemente, la parte que más sostiene la fiabilidad del
proyecto.

## Qué NO se financia / qué NO se hace
- No se venden ni ceden datos.
- No se perfilan usuarios (solo se analiza contenido **público**).
- La IA **no** decide ni atribuye; no sustituye la revisión humana.

## Estado y objetivos

- **Objetivo:** cubrir la base (~260 €/año). Las APIs y la ampliación de cobertura son
  **adicionales y variables**.
- **Vía de apoyo:** [Ko-fi](https://ko-fi.com/m_castillo) (recurrente). Verkami (campaña
  puntual) y NLnet (financiación de software libre) **en preparación**.
- **Progreso:** visible en la página de Ko-fi.

## Cambios

- 2026-09-25 — Añadida sección "Quién mantiene esto" (contexto de dedicación horaria, sin monetizar el tiempo).
- 2026-09-25 — Desglose inicial (servidor ~20 €/mes, dominio ~20 €/año, APIs variables).
