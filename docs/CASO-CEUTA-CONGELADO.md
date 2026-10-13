# Caso Ceuta — análisis CONGELADO (V1) y capa LIVE

> El caso Ceuta / Frontera Sur es el primer expediente del observatorio. Tiene **dos capas
> congeladas/separadas a propósito**: el **análisis (frozen)** y los **datos que siguen llegando
> (live)**. Este documento explica **qué se congela, qué sigue, de dónde se obtiene cada cosa y
> cómo evoluciona**.

## 1. Qué está congelado y qué no

| Capa | Qué es | ¿Cambia? | Dónde |
|---|---|---|---|
| **Frozen (V1)** | El **análisis** curado: embudo, candidatos, ráfagas, validación ciega, mapa y hechos con fuente, de la **ventana 30-jul → 21-sep-2026** (snapshot **1-oct-2026**). | **NO** (inmutable) | `docs/casos/ceuta-v1.json` (+ prosa en la página) |
| **Live** | Las **cifras actuales** del tema `frontera_sur` desde el 30-jul hasta hoy (eventos, autores, fuentes, URLs, clústeres, banda alta, clúster sostenido). | **Sí** (cada 6 h) | `event_temas` + `cluster_lineage` → inyectadas en la página y exportadas |

**Se congela el _análisis_, no la captura.** Los datos de Ceuta **siguen entrando** por el pipeline
normal (la captura del tema `frontera_sur` no se detiene).

## 2. Cómo siguen los datos (flujo)

```
captura (keywords frontera_sur)  ──▶  events  ──▶  event_temas (tema frontera_sur)
                                                   │
                                                   ├─▶ página /casos/ceuta/ (bloques LIVE, cada 6 h)
                                                   ├─▶ dashboard + informe visual/semanal del tema
                                                   ├─▶ API: /api/v1/tema/frontera_sur · …/serie · /api/export
                                                   └─▶ /datos/casos/ceuta.json  (sección "live")
```

- **Actualización:** paso **3f** del cron de 6 h (`update_caso_ceuta_live.py` + `export_caso_ceuta.py`).
- **Ventana:** `frontera_sur` usa **90 d** (config `temas.frontera_sur.ventana_dias`) para **conservar
  la historia del caso** aunque la ventana global sea de 45 d.

## 3. Dónde obtener los datos (después del congelamiento)

- **Análisis congelado (citable):** `https://fimi.viajeinteligencia.com/datos/casos/ceuta.json`
  (objeto `frozen`) + `…/ceuta-frozen.csv`. Lleva **`hash_frozen` = SHA-256** del bloque V1 →
  prueba de que no cambió.
- **Datos vivos:** el mismo JSON (objeto `live`), la **tabla viva** y el bloque «Cifras vivas» de la
  página, el **dashboard** y la **API** (`/api/v1/tema/frontera_sur`).
- **Export de evidencia:** `/api/export?cluster=<label>&fmt=csv|json|gexf`.

## 4. Cómo versionar (si hay que rehacer el análisis)

El V1 no se toca. Si procede un reanálisis (p. ej. nueva ventana), se publica **V2**:
1. Crear `docs/casos/ceuta-v2.json` (nuevo snapshot curado) y apuntar el exportador a él.
2. El nuevo `hash_frozen` quedará registrado; el V1 sigue consultable como histórico.
3. **Nunca** se edita el V1 in-place (rompería la prueba de inmutabilidad).

## 5. Por qué se congela

1. **Reproducibilidad/cita:** un informe con ventana y cifras fijas + hash es citable; una cifra
   móvil, no.
2. **La ventana viva caduca:** con ventana (45/90 d) las señales viejas salen del pipeline; el
   snapshot **preserva el origen del caso** (30-jul) aunque la captura viva ya no lo vea.
3. **Cumple la regla de encuadre:** «señal, no atribución»; el V1 lo dice de forma explícita y fechada.

## 6. Límites (heredados del V1)

Subconjunto observable (~2 % de URLs; Bluesky + prensa); el pico llega tras los hechos y lo domina
el **eco de prensa**; **0 coordinación confirmada**; la fase previa al 30-jul no es medible con esta
captura. El **origen** (movilización en Facebook/darija) lo documenta **Golden Owl**; este
observatorio mide el **eco** en España.
