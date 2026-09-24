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

## Limitaciones conocidas del sistema de hipótesis (23/Sep/2026)

1. **Umbral de estructura de H2 (`kcore`): corte sensible, no suave.** Sobre los
   clusters con `infra=100` (snapshot 23/Sep, 207):
   - `kcore=2` (par mutuo): **77** clusters.
   - `kcore=3` (frontera aplicada): **46** clusters.
   - `kcore>=4` (endurecido): **81** supervivientes de 207.

   **Corregido el 24/Sep/2026.** El gate original exigía solo `kcore_size>=3`
   (el TAMAÑO del núcleo), lo que permitía **núcleos no mutuos** (1-cores:
   cadenas/estrellas con `kcore=1`) colarse como "estructura". Detectado en
   `frontera_sur_cluster_022` (3 cuentas, `kcore=1`, `kcore_size=3`, **H2=76 %**
   antes del fix pese a no tener núcleo mutuo). El nuevo gate es
   **`kcore>=2 AND kcore_size>=3`** (núcleo **mutuo** de ≥3 cuentas), **alineado
   con el criterio del badge visual `_kcore_chip`** (que ya usaba `kcore>=2` y
   hasta ahora discrepaba del gate de scoring). Efecto sobre el corpus: **47 de
   803 clusters (22 con `infra=100`) pasan de H2 a H2b**. `overall_score`/banda
   **NO** cambian (solo `hypotheses_json`).

2. **Caso sintético (h) explorado y descartado.** Se probó si H2 podía dispararse
   con `sync` artificialmente bajo (`sync=10`) e `infra=100`. Conclusión:
   **inalcanzable con datos reales** — `sync = min(100, coordination_score·12)`
   tiene un **suelo estructural de 36** para cualquier cluster detectado
   (`coordination_score` mínimo por diseño del pipeline). No se añade un gate
   `sync_min` adicional por no corregir un problema inexistente en producción.

3. **Empate exacto H2 = H3** (caso `sync=50, anom=50, net=50, infra=100`: ambas
   0.500). El desempate es hoy por **orden de inserción del diccionario**, sin
   criterio explícito documentado. No afecta a `overall_score`/banda; solo a qué
   etiqueta se muestra primero en el (raro) caso de empate exacto. **Pendiente**:
   definir criterio de desempate si se observa en producción.

4. **Asimetría de pesos sin justificar entre H2 y H2b.**
   `H2 = struct·(sync·0.55 + (1−anom)·0.45)` frente a
   `H2b = (1−struct)·(sync·0.65 + (1−anom)·0.35)`: los coeficientes difieren
   (0.55/0.45 vs 0.65/0.35) sin una razón de diseño documentada. Menor, anotado
   para revisión futura.

5. **Redundancia H5/H2b.** Ambas capturan "sincronía sin estructura" con
   solapamiento alto (ejemplo sintético: **0.885 vs 0.87** sobre el mismo caso);
   solo se distinguen por el término de diversidad de URLs. Ya identificado como
   parte de la **versión "completa" pendiente del fix de H5** (pasar `tema`/flag
   electoral a `classify_hypotheses`), sin implementar; se referencia aquí para
   trazabilidad.

## Regla de lectura

Antes de afirmar "campaña extranjera" se necesita, como mínimo, UNA de estas:
(a) infraestructura compartida sostenida + volumen + anomalía (estructural),
(b) evidencia organizativa (dominio/creación de cuentas/financiación), o
(c) la combinación de varias hipótesis consistentes. La ausencia de (a), (b) y
(c) debe reportarse como UNKNOWN — y UNKNOWN es un resultado válido y honesto.
