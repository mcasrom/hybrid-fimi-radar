# Atribución en el radar FIMI: qué se mide, qué NO, y por qué UNKNOWN es válido

Documento de límites de la capa de atribución (complementa TRAZABILIDAD.md y el
bloque "Metodología" del dashboard). Fecha: 05/Sep/2026.

## Qué hace la atribución hoy

El módulo `attribution/attribution.py` evalúa 6 hipótesis (H1-H6) a partir de
señales ESTRUCTURALES de comportamiento coordinado:

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

## Regla de lectura

Antes de afirmar "campaña extranjera" se necesita, como mínimo, UNA de estas:
(a) infraestructura compartida sostenida + volumen + anomalía (estructural),
(b) evidencia organizativa (dominio/creación de cuentas/financiación), o
(c) la combinación de varias hipótesis consistentes. La ausencia de (a), (b) y
(c) debe reportarse como UNKNOWN — y UNKNOWN es un resultado válido y honesto.
