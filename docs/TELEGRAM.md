# Telegram público — piloto `protestas_juveniles`

## Qué se captura

Solo **canales públicos** accesibles por `https://t.me/s/<canal>`. No se capturan grupos privados, mensajes directos ni cuentas personales. El collector usa el HTML público, sin login ni API key.

## Canales (12 nuevos + 6 existentes)

Los 12 del piloto están en `data/telegram_protestas.yaml`; son públicos y se verificaron el **26-oct-2026**:

- España: EL PAÍS, eldiario.es, LaSexta, Público, El Confidencial, El Periódico política.
- Francia: FRANCE 24.
- Italia: la Repubblica.
- Serbia: Danas.
- Balcanes: Balkan Insight.
- Internacional: Bellingcat, The Guardian.

Los seis ya existentes (`elfarodeceuta`, `maldita_es`, `sahelbrut`, `meduzalive`, `AlMayadeenEnglish`, `PressTV`) se mantienen.

No hay canal albanés público con contenido visible en la muestra probada; no se inventa uno.

## Esquema `tg:`

Cada evento guarda:

| Campo | Valor |
|---|---|
| `author` | `tg:<canal>` |
| `source` | `telegram:<canal>` |
| `timestamp` | fecha del mensaje |
| `text` | texto del post (máx. 500) |
| `url` | `https://t.me/<canal>/<post_id>` |
| `action` | `post` |

No se guardan teléfonos, miembros ni identificadores privados de usuarios. La atribución es al **canal**, no a una persona.

## Validación

```bash
.venv/bin/python scripts/check_telegram.py
```

El checker no escribe en la base; solo comprueba HTTP, título y mensajes visibles. El collector corre en el ciclo de 6 h y el tema filtra por sus keywords.

## Límites

- Un canal público no es una muestra representativa de Telegram.
- El HTML de `t.me/s/` puede cambiar o limitar peticiones; el collector registra el error y sigue.
- No se usan grupos privados ni automatización de cuentas.

## Vigilancia de volumen

Línea base al añadir los canales (26-oct-2026): **79 eventos Telegram/24 h** y **1.001/14 d**, ≈**1,1 %** del corpus.

El monitor `detection/monitor_telegram.py` corre tras la captura y avisa solo al cambiar de nivel:

| Nivel | 24 h | 6 h | Cuota del corpus 24 h |
|---|---:|---:|---:|
| Aviso | 300 | 100 | 5 % |
| Crítico | 650 | 220 | 10 % |

También avisa si un canal supera **100 eventos/24 h** (aviso) o **180** (crítico). El estado se guarda en `data/telegram_volume_state.json` para no repetir el mismo aviso.

**Tope duro:** `TG_MAX_PER_CYCLE = 360` en `collectors/capture.py`, equivalente a 18 canales × 20 mensajes. Al contar mensajes descargados (no solo los que pasan el filtro), un tope menor saltaba Bellingcat y The Guardian; ahora se leen todos. El monitor sigue midiendo solo eventos guardados.

**Interruptor manual:** si un canal se dispara, comentar su línea en `config.yaml → telegram_canales` o en `data/telegram_protestas.yaml`; el siguiente ciclo deja de leerlo. No hay que reiniciar servicios.

Comandos:

```bash
.venv/bin/python detection/monitor_telegram.py --json
.venv/bin/python detection/monitor_telegram.py --tg
.venv/bin/python scripts/check_telegram.py
```
