# Taxonomía FIMI Radar

Documento marco de la estructura temática del radar. Define **qué es un tema**,
**qué es una narrativa**, **cómo se agrupan** y **cómo se separan** del dato, la
señal y la atribución. Es el punto de partida de la ampliación temática (Fase A
de la matriz de temas).

## Principio

> El radar no decide qué es verdad. Observa **comportamiento informativo**.

El sistema no añade ni cierra temas solo. La taxonomía es estable; el catálogo
vivo (`config.yaml → temas`) la implementa y lo decide el administrador.

## Tres niveles de estructura

| Nivel | Qué es | Dónde vive |
|---|---|---|
| **Familia** | Gran dominio (crisis, instituciones, recursos, tecnología, sociedad) | Este documento |
| **Tema** | Área monitorizada con captura propia y línea base | `config.yaml → temas` |
| **Narrativa** | Relato concreto que puede cruzar temas/familias | Calculado (`narrativas_alineadas`, `findings`) |
| **Subtema / palabra clave** | Términos de captura | `config.yaml → keywords` |

**Regla:** un *tema* es una superficie de observación; una *narrativa* es un
objeto que se mueve entre temas. No se confunden: "Frontera Sur" es un tema; "la
exculpación de Marruecos" es una narrativa que puede aparecer en Frontera Sur,
en Geopolítica UE-Marruecos y en Política nacional.

## Familias transversales (A–E)

| Id | Familia | Contenido |
|---|---|---|
| A | Crisis | Frontera, guerra, atentado, incendio, inundación, apagón, desastre |
| B | Instituciones | Gobierno, UE, OTAN, elecciones, justicia, policía, FF.AA. |
| C | Recursos estratégicos | Petróleo, gas, agua, alimentos, minerales, cables, puertos, estrechos |
| D | Tecnología | IA, deepfakes, ciberataques, satélites, drones, redes sociales |
| E | Sociedad | Inmigración, identidad, polarización, protestas, desigualdad, confianza |

## Mapa de los temas activos

| Tema (`config.yaml`) | Estado | Familias | Subtemas principales |
|---|---|---|---|
| `frontera_sur` | producción | A, E | Ceuta, Melilla, Canarias, migración, relaciones España-Marruecos |
| `geopolitica_ue_marruecos` | producción | B, C | diplomacia UE-Magreb, acuerdos bilaterales |
| `politica_nacional` | producción | B, E | gobierno/oposición, justicia, polarización |
| `eeuu_politica` | producción | B, D | midterms 2026, interferencia electoral, desinformación |
| `oriente_medio` | producción | A, C | Gaza, Irán, Ormuz, Líbano, escalada regional |
| `sahel` | piloto | A, E | Mali, Níger, Burkina, AES, yihadismo, migración |

> Nota: el catálogo real es el de `config.yaml`, no una lista teórica. Cualquier
> propuesta de tema nuevo se valida contra datos antes de darlo de alta
> (`temas_cli.py alta --verifica`).

## Ejes transversales (categorías que cruzan temas)

No son temas: son **lentes** que se aplican sobre el volumen existente para ver
una dimensión compartida. Se calculan sin captura nueva (`detection/indicadores.py`).

| Eje | Descripción | Reporta |
|---|---|---|
| Elecciones e interferencia democrática | narrativas de fraude, deslegitimación, ataques a instituciones | volumen, fuentes, temas donde aterriza |
| Energía / precios | petróleo, gas, inflación energética | volumen, fuentes, temas |
| Clima / agua / incendios | sequía, embalses, DANA, incendios | volumen, fuentes, temas |
| Ciberseguridad e información | ciberincidente → narrativa → reacción | volumen, fuentes, temas |

Un eje con volumen alto y multi-fuente es candidato a **tema propio** (decisión
humana), pero por defecto se observa como lente transversal.

## Modelo de niveles (dato → atribución)

```
OBSERVACIÓN → ANOMALÍA → AMPLIFICACIÓN → COORDINACIÓN → CAMPAÑA POTENCIAL → ATRIBUCIÓN
```

- La atribución **solo** con evidencia independiente. `UNKNOWN` es un resultado válido.
- Cada nivel se calcula por separado; el score NO es la atribución.
- Un aumento de narrativa no es una campaña; una anomalía no es coordinación.

## Indicadores explícitos (amplificación y coordinación)

Se exponen como indicadores narrados, separados del score (ya presentes como
componentes del assessment):

- **Amplificación**: nº de cuentas, nº de URLs distintas, nº de fuentes, ventana temporal.
- **Coordinación**: sincronía temporal (tight-timing) + reutilización de contenido + infraestructura.
- **Salto de dominio**: la misma narrativa aparece en ≥2 familias distintas.

## Reglas de neutralidad

- Agnosticismo respecto al actor político.
- Separación estricta dato / señal / hipótesis / atribución.
- No confundir popularidad con coordinación ni sincronía con operación.
- No etiquetar una posición política como desinformación por su contenido.
- Presentar incertidumbre cuando la evidencia es insuficiente.
- Registrar la evidencia que sustenta cada alerta (`cluster_events`, export).

## Fases de ampliación

1. **Fase A (esta):** taxonomía + separación tema/narrativa + indicadores
   explícitos + ejes transversales + tendencias (candidatos con delta temporal).
2. **Fase B:** un tema nuevo de máximo ROI (Energía) con feeds y medición de
   memoria obligatoria antes de merge.
3. **Fase C (diferenciadora):** análisis transversal de narrativas que migran de
   dominio (`geopolítica → energía → economía → migración → política`). Priorizar
   por encima de "más temas"; es el encaje de la hipótesis de producto abierta.
