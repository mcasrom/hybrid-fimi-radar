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
