# Rúbrica de «coordinación observable» — versión 1 (30-Sep-2026)

**Por qué existe:** la validación ciega dio **κ=0,30 (débil)** en coordinación. Al revisar los
desacuerdos, la causa no era el dato sino **la definición**: el revisor 1 marcó «sí» en tres
clusters de **3 cuentas / 1 solo dominio / ventanas de 300-400 h** que eran **automatización de
una sola mano** — es decir, cada revisor aplicaba su propia idea de «coordinación».

Esta rúbrica **fija una definición operativa y objetiva** para que dos personas (y el sistema)
midan lo mismo. **Sustituye** a la noción laxa usada en la V1; hay que **re-medir** con ella.

---

## 1. Definición operativa

Un cluster muestra **`coordinacion_observable = si`** si cumple **las tres** condiciones:

1. **Misma pieza en cuentas distintas** — la **misma URL** o un **texto casi idéntico**
   (solape ≥70 %) publicado por **≥2 cuentas distintas**.
2. **Ventana corta** — esas publicaciones caen dentro de **≤24 h** (para `si`, idealmente **≤6 h**;
   6-24 h → `si` solo si el resto es nítido, si no `dudoso`; **>72 h → `no`**).
3. **Cuentas independientes (no una sola mano)** — **no** es ninguno de estos:
   - **feed de una fuente**: una cuenta/dominio concentra casi todo (>55 % / >80 %);
   - **sindicación**: el mismo texto repartido por una **red de medios o de dominios propios**;
   - **automatización de una red**: cuentas del **mismo PDS/handle** (`*.pds.<x>`), bots lúdicos, plantillas masivas;
   - **eco de prensa**: la mayoría de enlaces son de **medios establecidos**.

Si 1 y 2 se cumplen pero hay duda sobre 3 → **`dudoso`**. Si falta 1 o 2 → **`no`**.

> **En una frase:** «cuentas **distintas e independientes** empujando **la misma pieza** en **pocas
> horas**» = coordinación observable. Un feed, una sindicación o una red de bots **no** lo son
> (se etiquetan aparte, ver §2).

## 2. Capas separadas (no confundir)

| Etiqueta | Pregunta | Ejemplo |
|---|---|---|
| `coordinacion_observable` | ¿Cuentas **distintas e independientes** con **la misma pieza** en **≤24 h**? | burst real |
| `inautenticidad` | ¿La conducta parece **fabricada / de una sola mano** (aunque sea benigna)? | red `⚖️🏛️` en varios dominios |
| `intencion` | ¿Hay indicios de **querer influir** (no mera coincidencia)? | — |
| `dimension_extranjera` | ¿Indicio de **actor extranjero**? | — |
| `fimi` | ¿**Prueba confirmada** de FIMI? | casi siempre `no` |

Una red automatizada puede ser **`inautenticidad=si`** y **`coordinacion_observable=no`** (es una
sola mano, no actores independientes). **No mezclar las capas.**

## 3. Ejemplos reales (de la V1)

- **`energia_cluster_015`** — 3 cuentas, **1 dominio**, ventana **409 h**, «posts idénticos
  plantilla (emoji)». → `coordinacion_observable = **no**` (automatización de una sola mano,
  ventana larga); `inautenticidad = si`.
- **`elecciones_cluster_045`** — 3 cuentas, 1 dominio killbait, 44 URLs propias, ventana 367 h.
  → `coordinacion_observable = **no**` (feed/aggregator); `inautenticidad = dudoso`.
- **`frontera_sur_cluster_008`** — 7 cuentas `es-*.pds.netasga`, mismo texto, 0,19 h.
  → `coordinacion_observable = **no**` (mismo PDS = red de una mano); `inautenticidad = si`.
- **Burst de cuentas independientes con la misma pieza en ≤6 h** → `coordinacion_observable = **si**`.

## 4. Reglas de `dudoso` (úsalo, es información)

- Ventana 6-24 h y el resto nítido → `dudoso` si no hay seguridad sobre la independencia.
- No se puede ver el texto/URL de la pieza → `dudoso`.
- Cuentas que podrían ser la misma persona con varios alias → `dudoso` (o `inautenticidad=si`).
- Ante la duda entre `si` y `no` → `dudoso`, **no** fuerces.

## 5. Protocolo

1. Rellena **primero** `coordinacion_observable` (con 1-2-3); **después** las otras capas.
2. Mira `textos_evidencia` y `urls_evidencia`; el nº de cuentas/eventos **no basta**.
3. **Independencia**: no hables con el otro revisor ni veas sus etiquetas.
4. Con dos revisiones: `detection/validacion_kappa.py --a <rev1> --b <rev2>` (κ + matriz + precisión).

## 6. Qué cambia

- El anterior «8,3 % de coordinación» se midió con la definición laxa → **queda superado**; hay que
  **re-etiquetar** (o reinterpretar) con esta rúbrica y volver a calcular κ y precisión.
- El **sistema** ya aplica criterios equivalentes (`cross_account_synchrony` + ventana + no
  dominante + señales de automatización/sindicación): la rúbrica **alinea al humano con el código**,
  que es lo que sube el κ.


---

## Aplicación mecánica (30-Sep) — resultado

Aplicada por el propio sistema a los 40 de la muestra: **0 coordinación**. Acuerdo con rev1 **92 %**
/ rev2 **86 %**, pero **κ=0,00 degenerado** (el sistema es constante → κ no informa). Los **únicos
desacuerdos son los «sí» humanos**, que son **ventanas de 300-400 h y 1 dominio** (automatización/feed)
→ la rúbrica los reclasifica a `no`.

**Lectura:** bajo la rúbrica estricta, la banda HIGH **no contiene coordinación observable**; las
ráfagas del corpus son **sindicación/automatización** (→ `inautenticidad`). Dos implicaciones:
1. El criterio **ventana ≤24 h** es el que manda casi todo a `no`. Conviene separar dos etiquetas:
   **`burst` (≤24 h)** vs **`sustained` (>72 h)** — no mezclarlas.
2. El κ humano seguirá débil si la definición no se comparte; con la rúbrica, el desacuerdo se
   concentra en la **capa** (coordinación vs automatización), no en el hecho.


---

## Refinamiento v2 (30-Sep): **dos etiquetas** en vez de una

El criterio de ventana mezclaba dos fenómenos distintos. Se separan:

### `burst` — ráfaga coordinada
`si` si: **misma pieza** en **≥2 cuentas distintas e independientes** y **ventana ≤24 h**
(idealmente ≤6 h), **sin una sola mano** (no feed/sindicación/red de PDS/eco de prensa).
→ Corresponde a `cross_account_synchrony` en el sistema.

### `sustained` — eco sostenido **con volumen** (definición cerrada 30-Sep)
`si` si **TODO**:
- **misma pieza o misma narrativa** (URL idéntica o texto ≥70 %) en **≥3 cuentas distintas e independientes**;
- **ventana >72 h**, **sin una sola mano** (no feed/sindicación/red de PDS/eco de prensa);
- **volumen sostenido**: **≥10 eventos repartidos en ≥3 días distintos** (ritmo ≥1/día).

**No** es `sustained` «la misma pieza compartida una vez cada muchos días» (sin volumen): eso es
**eco lento** → `no`. La diferencia es **flujo**, no persistencia. → Corresponde a
`sustained_amplification` del sistema (que exige ≥5 cuentas + contenido similar + >72 h).

### Zona intermedia (24-72 h)
→ `dudoso` (o se etiqueta aparte como `intermedio`).

**Cada una se mide por separado** (κ propio). Una ráfaga es lo que parece: un pico en horas;
el eco sostenido es otra cosa y no debe hundir el acuerdo de la ráfaga.

### Protocolo de re-etiquetado
La muestra gana **dos columnas** (`label_burst`, `label_sustained`, valores `si`/`no`/`dudoso`).
El revisor **no** las deriva de mirar solo la ventana: comprueba **misma pieza + independencia**.
Luego: `validacion_kappa.py` un κ por columna.


### Resultado mecánico v2 (30-Sep)

Clasificación objetiva por cluster (misma pieza + independencia + ventana):
Con `sustained` **cerrado por volumen** (≥10 eventos en ≥3 días distintos):
- **Muestra (40):** burst **0** · sustained **6 (15 %)** · eco_lento **2 (5 %)** · no **32 (80 %)**.
- **Banda HIGH (100):** burst **1 (1 %)** · sustained **21 (21 %)** · eco_lento 1 · intermedio 1 · no **76 (76 %)**.
  (El único «burst» — `elecciones_cluster_006` — es en realidad la **sindicación**.)
- **Humano (una revisión):** burst **0** · sustained **0** → **acuerdo total en `burst`**; el humano
  es **más estricto** en `sustained` (no considera «eco sostenido» ni 10-100 eventos repartidos en días).

**Cruce con los humanos** (muestra): los dos «sí» que coinciden (`si|si`) son **`no` mecánico**
(feeds de una sola fuente); el `sustained` mecánico son casi todos «no» para los humanos.
→ **El desacuerdo es de CAPA** (llamar «coordinación» a un feed/eco), **no de hecho**.
→ Re-etiquetar con la rúbrica debe concentrar el acuerdo en `burst`/`sustained` **objetivos**.

**Muestra nueva:** `data/validacion/muestra_high_blind_20260930_burstsustained.csv`
(2 columnas `label_burst` / `label_sustained`, 40 filas, sin etiquetas).
