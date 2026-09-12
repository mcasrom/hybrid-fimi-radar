# Gobernanza del ciclo de vida de los temas

El radar FIMI **no decide**. Observa, mide, sugiere y avisa; **toda transición de estado
la toma una persona** y queda registrada en la bitácora. Este documento describe el ciclo
de vida de un tema, los criterios objetivos de promoción y cierre, cómo se avisa y quién
ejecuta cada acción.

## Principio rector

> El sistema propone; el dueño decide. Ninguna promoción ni cierre ocurre de forma
> automática. El radar solo marca cuándo se cumplen unos criterios medibles y avisa.

Esto evita dos riesgos: (1) que un tema "ruidoso" pase a producción sin validación, y
(2) que un tema se cierre por una racha mala sin revisión humana.

## Estados

| Estado | Significado |
|---|---|
| `piloto` | Tema **en calibración**. Se observa con cautela; su panel muestra un aviso de "lectura con cautela" y, si procede, un aviso de riesgo de sesgo. |
| `produccion` | Tema **validado**. Superó la ventana de promoción y se muestra como el resto del catálogo. |
| `candidato_a_cierre` | El radar detectó que el tema cumple criterios de cierre (ver abajo). **Sigue operando** hasta que una persona decida. |
| `cerrado` | Tema **retirado**. El pipeline deja de capturarlo; sus datos quedan en la BD (retención) y la evidencia se exporta a `data/export/`. |

El paso por estos estados se registra en la tabla `bitacora` (inicio, cambios de estado,
sugerencias del sistema y notas manuales).

## Alta (nuevo tema)

Un tema nuevo nace siempre en **`piloto`**. Se da de alta con `detection/temas_cli.py alta`
(definiendo sus keywords) o editando `config.yaml`. Se observa sin prometer señal.

## Promoción: piloto → producción

**Quién comprueba:** `detection/check_promocion.py`, ejecutado por el cron cada 6 h para
cada tema en estado `piloto`.

**Criterios** (todos deben cumplirse):

1. **Ventana de observación** ≥ **72 h** (`FIMI_PROMOCION_H`).
2. **Ciclos de snapshot** completos y exitosos ≥ **8** (`FIMI_PROMOCION_MIN_CICLOS`).
   Se cuentan las secciones `=== run_fimi tema=<tema> ===` del log que no acabaron en error.
3. **Sin errores nuevos** de pipeline durante la ventana. Un error nuevo **reinicia** la
   ventana (y avisa).

**Cómo avisa:** al cumplirse, envía **un mensaje por Telegram** al dueño (chat
`FIMI_PROMOCION_CHAT`, por defecto `47652516`) con el resumen (ciclos, horas, clusters
actuales) y el paso a ejecutar. El aviso es **único** por episodio (no re-notifica).

**Qué ve el usuario:** en el dashboard, el tema muestra el badge **«✅ Lista para
producción · gestionar»**; en el panel de administración se **activa el botón «⬆️ Promover»**
(deshabilitado mientras no se cumplan los criterios, con tooltip explicativo).

**Quién ejecuta:** una persona, desde el **panel de administración** o por CLI:
```
python detection/temas_cli.py --estado <tema> produccion
```

**Estado persistido:** `data/promocion_<tema>.json`
(`inicio`, `ready`, `notificado_ready`, `ciclos`, `errores`, `ventana_h`, `min_ciclos`).

## Cierre: sugerencia, nunca decisión

**Quién comprueba:** `detection/check_cierre.py`, ejecutado por el cron cada 6 h.

**Criterios** (ventana de **21 días**, `FIMI_CIERRE_VENTANA_DIAS`; solo se evalúa tras
≥ **14 días** de operación, `FIMI_CIERRE_MIN_DIAS`):

1. **Volumen bajo**: promedio de hallazgos/día < **2,0** (`FIMI_CIERRE_FINDINGS_POR_DIA`).
2. **Piloto estancado**: un tema en `piloto` lleva > **90 días** (`FIMI_CIERRE_PILOTO_DIAS`)
   sin superar la ventana de promoción.

**Anulan la candidatura** (no es candidato a cierre):

- **Señal clara**: el último cluster del tema tiene score ≥ **60** (`FIMI_CIERRE_SENAL`).
- El tema está **`ready`** para promoción.

**Cómo avisa:** **Telegram** al dueño (chat `FIMI_CIERRE_CHAT`, por defecto `47652516`) +
una **sugerencia** en la bitácora (origen `sistema`). Aviso **único** por episodio; se
rearma si el tema se recupera.

**Qué ve el usuario:** badge **«🗂 Candidata a cierre · gestionar»** en el dashboard.

**Quién ejecuta:** una persona, desde el panel o por CLI:
```
python detection/temas_cli.py --cerrar <tema> --nota "motivo"
```
Al cerrar: **exporta la evidencia** a `data/export/`, marca `estado: cerrado` (el pipeline
lo salta) y lo registra en la bitácora. **No destruye la BD** (los datos siguen, con la
retención habitual).

## Reapertura

Un tema cerrado puede volver a `piloto` en cualquier momento:
```
python detection/temas_cli.py --estado <tema> piloto --nota "reactivar por señal"
```

## Dónde se ve

- **Dashboard** (público): pestaña *Transparencia* → card **"Ciclo de vida de un tema y
  gobernanza"**; badge de estado en la tarjeta del tema; **Bitácora** con el historial.
- **Panel de administración** (`/admin.html`, privado): sección **"Gestión de temas"** con
  el **progreso de la ventana** (`X/72 h · N/8 ciclos · errores`), la señal
  (lista para producción / candidata a cierre), los motivos de cierre y los botones
  Promover / Cerrar / Reabrir. Requiere `x-admin-secret`.

## Variables configurables

| Variable | Defecto | Uso |
|---|---|---|
| `FIMI_PROMOCION_H` | 72 | Horas de observación antes de promocionar |
| `FIMI_PROMOCION_MIN_CICLOS` | 8 | Ciclos de snapshot mínimos |
| `FIMI_PROMOCION_CHAT` | 47652516 | Chat de Telegram del dueño (promoción) |
| `FIMI_CIERRE_VENTANA_DIAS` | 21 | Ventana de evaluación de cierre |
| `FIMI_CIERRE_FINDINGS_POR_DIA` | 2.0 | Umbral de volumen (hallazgos/día) |
| `FIMI_CIERRE_MIN_DIAS` | 14 | Días mínimos de operación antes de evaluar |
| `FIMI_CIERRE_PILOTO_DIAS` | 90 | Días de piloto sin promocionar |
| `FIMI_CIERRE_SENAL` | 60 | Score que anula la candidatura a cierre |
| `FIMI_CIERRE_CHAT` | 47652516 | Chat de Telegram del dueño (cierre) |

## Ficheros y trazabilidad

- `data/promocion_<tema>.json` — estado de la ventana de promoción por tema.
- `data/cierre_<tema>.json` — candidatura a cierre y motivos.
- Tabla `bitacora` (en `data/radar.db`) — historial permanente de estados.
- `detection/check_promocion.py`, `detection/check_cierre.py`, `detection/temas_cli.py`,
  `detection/bitacora.py` — implementación.
