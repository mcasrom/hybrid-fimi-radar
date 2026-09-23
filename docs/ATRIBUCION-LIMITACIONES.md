# Atribución en el radar FIMI: qué se mide, qué NO, y por qué UNKNOWN es válido

Documento de límites de la capa de atribución (complementa TRAZABILIDAD.md y el
bloque "Metodología" del dashboard). Fecha: 05/Sep/2026.

## Qué hace la atribución hoy

El módulo `attribution/attribution.py` evalúa 7 hipótesis (H1, H2, H2b, H3, H4,
H5, H6) a partir de señales ESTRUCTURALES de comportamiento coordinado:

- sincronización temporal (mismo contenido/enlaces casi a la vez),
- contenido casi duplicado,
- amplificación (cuántas cuentas repiten la misma pieza),
- infraestructura compartida (mismos dominios/URLs),
- densidad de red,
- anomalía (desviación del comportamiento esperado).

El resultado es una etiqueta de la taxonomía NEUTRA al actor
(UNKNOWN / NO_ATTRIBUTION / DOMESTIC / FOREIGN / ...) con una confianza
(NO/LOW/MEDIUM/HIGH). El radar es AGNÓSTICO AL ACTOR por diseño: primero se
observa la anomalía conductual; atribuir un actor concreto exige más evidencia
de la que estas señales aportan.

## Qué NO hace (limitaciones)

1. **No incorpora evidencia organizativa** (salvo el módulo whois_signal.py,
   ver abajo): no consulta WHOIS/RDAP de registro, no analiza patrones de
   creación de cuentas, no rastrea financiación ni vínculos declarados.
2. **UNKNOWN/NO_ATTRIBUTION ≠ "no hay campaña"**. Con los datos actuales
   44/44 clusters activos son UNKNOWN. Eso no significa que no exista campaña:
   significa que la evidencia ESTRUCTURAL sola no permite distinguir entre
   viralización orgánica, coordinación partidista legítima, amplificación
   mediática u operación extranjera.
3. **La atribución no se mejora añadiendo más fuentes RSS.** Si la señal de
   quién está detrás no se busca, más feeds solo aportan más contenido a
   puntuar, no más capacidad de atribuir. Por eso la hoja de ruta prioriza
   señales organizativas (RDAP) ANTES de ampliar el catálogo de fuentes.
4. **El score de banda (NORMAL..CRITICAL) es una señal conductual**, no una
   condena: un cluster HIGH indica comportamiento coordinado anómalo entre esas
   cuentas, no prueba de orquestación ni de actor extranjero. El dashboard lo
   advierte con la guardia de interpretación en cada tarjeta HIGH/CRITICAL.
5. **El piso híbrido de masa (05/Sep)** marca como "posible ruido de bajo
   volumen" los clusters con <3 cuentas y volumen bajo: la pareja de dos cuentas
   sincronizadas NO debe leerse como red orquestada a gran escala. Un cluster de
   2 cuentas no llega a CRITICAL salvo infraestructura compartida confirmada.

## Señal organizativa de bajo coste: whois_signal.py (RDAP)

`detection/whois_signal.py` consulta RDAP (registro WHOIS moderno, HTTP
público, sin API key) de los dominios que los clusters HIGH/CRITICAL comparten
de forma dominante y devuelve:

- fecha de registro del dominio,
- transferencia / re-registro recientes (posible cambio de manos),
- registro con privacidad/proxy (reduce trazabilidad),
- registrante declarado.

Es evidencia DÉBIL de apoyo, no atribución: un dominio reciente o con
privacidad NO identifica a un actor. Se usa para enriquecer la lectura del
analista y alimentar la decisión de profundizar en un cluster, no para emitir
un veredicto. Verificación real (05/Sep): eldiario.es/elpais.com/lemonde.fr
salen "dominio estable" (medios consolidados); el dominio activista pro-saharaui
noteolvidesdelsaharaoccidental.org sale con privacidad/proxy y transferencia
2023 — señal organizativa que las señales estructurales no capturaban.

## Recalibración de hipótesis (23/Sep/2026): H2/H2b y renombrado de H5

Motivo: al comparar `frontera_sur_cluster_005` (lineage
`frontera_sur_cluster_010@1789928930`) con un análisis externo con búsqueda web,
se detectaron dos problemas de **DISEÑO** (no de datos):

1. **H5 "Campaña política" no medía política.** Su fórmula era
   `sync*0.40 + div*0.35 + (1-infra)*0.25`: sincronía + diversidad de URLs −
   infraestructura. **No contenía ninguna señal política ni electoral.**
   Corregido por **renombrado** ("Sincronía sostenida con contenido diverso / sin
   estructura"), **sin cambiar la fórmula**. (La versión "completa" — exigir
   contexto político real — queda pendiente.)
2. **H2 "Campaña coordinada doméstica" disparaba sin estructura.** Antes:
   `sync*0.45 + (1-infra)*0.30 + (1-anom)*0.25` premiaba la BAJA infraestructura,
   de modo que clusters de 1-2 cuentas compartiendo enlaces de prensa (eco)
   salían como "campaña coordinada doméstica".

Criterio aplicado:

- `struct = infra/100` **si `kcore_size >= 3`, si no `0`**. Exigir un **núcleo
  mutuo de ≥3 cuentas** (k-core del grafo de coordinación) como evidencia de
  estructura REAL evita etiquetar el **eco de prensa** de 1-2 cuentas como
  campaña coordinada.
- **H2 = struct · (sync·0.55 + (1−anom)·0.45)** — solo con estructura.
- **H2b (nueva) = (1−struct) · (sync·0.65 + (1−anom)·0.35)** — "Sincronización
  sin atribución de operador": alta sincronía temporal SIN estructura (no
  atribuye operador).

Dry-run (23/Sep): de los clusters con `infra=100` (203), **127 mantienen H2** y
**76 caen a H2b** (comprobados como eco de prensa de 1-2 cuentas, no falsos
negativos). `overall_score` y **banda NO cambian** (las hipótesis no alimentan el
scoring; solo `assessments.hypotheses_json`).

## Regla de lectura

Antes de afirmar "campaña extranjera" se necesita, como mínimo, UNA de estas:
(a) infraestructura compartida sostenida + volumen + anomalía (estructural),
(b) evidencia organizativa (dominio/creación de cuentas/financiación), o
(c) la combinación de varias hipótesis consistentes. La ausencia de (a), (b) y
(c) debe reportarse como UNKNOWN — y UNKNOWN es un resultado válido y honesto.
