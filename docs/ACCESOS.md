# Accesos al observatorio: humanos frente a máquinas

Registro histórico de quién entra en `fimi.viajeinteligencia.com`, separando
lectura humana de tráfico automatizado. Nace de un problema concreto: el log de
nginx rota a los 14 días y el informe diario era un texto que se enviaba y se
perdía, así que no había forma de responder "¿cuánta gente ha leído esto?".

## Qué hay aquí

| Pieza | Dónde |
|---|---|
| Clasificador + ingesta + SQLite | `detection/accesos.py` |
| CLI | `scripts/fimi_accesos.py` |
| Test de regresión | `tests/test_accesos.py` |
| Base | `data/accesos.db` (SQLite, acumulativa) |
| Salt de seudonización | `data/accesos.salt` (600) |
| Daily list | `data/listas/AAAA-MM-DD.md` |
| Cron | `/home/deploy/scripts/cron_accesos.sh` → 40 7 * * * |

## Uso

```bash
cd /home/deploy/hybrid-fimi-radar
.venv/bin/python scripts/fimi_accesos.py ingest              # lee lo nuevo
.venv/bin/python scripts/fimi_accesos.py ingest --stats      # + resumen
.venv/bin/python scripts/fimi_accesos.py daily --todos       # regenera todo
.venv/bin/python scripts/fimi_accesos.py stats               # por día
.venv/bin/python scripts/fimi_accesos.py lectores             # histórico
.venv/bin/python scripts/fimi_accesos.py reset --confirmar   # rebaca
```

`ingest` es **idempotente**: guarda un cursor por fichero `(inodo, offset)`, así
que se puede lanzar cada hora. Si rotó el log, el inodo cambia y se relee desde
el principio; los `.gz` ya completos se saltan.

## Las cinco categorías

`INTERNAL` · `DUENO` · `API` · `BOT` · `HUMANO_PROBABLE`

- **INTERNAL** — canario propio, healthchecks, monitor. Nunca es un lector.
- **DUENO** — tu navegador. Humano, pero no es lectura: se cuenta aparte para no
  inflar la cifra titular.
- **API** — cualquier `/api/…`. Es una interfaz de máquinas aunque la pida una
  IP residencial. `/api.html` (la documentación) sí es de gente.
- **BOT** — crawler, escáner, 404, o red de hosting.
- **HUMANO_PROBABLE** — navegador, 200, IP que no es tuya ni una nube. **No es
  una persona probada**: es un candidato, y el daily separa los que sí leen.

## Lector vs. candidato

Un `GET /` no demuestra que haya alguien detrás. Solo cuenta como **LECTOR** si
abre contenido, o si vuelve con calma:

- abrió contenido (`/research.html`, `/glosario.html`, `/c/<id>`, …), o
- resolvió 3+ rutas distintas a lo largo de 2+ días, o
- volvió 3+ días.

Se descartan antes:

- **ráfaga** — 3+ páginas en menos de 90 s es un automat, no una lectura;
- **mixto** — si esa IP tiene alguna petición clasificada como bot, no es
  lectura limpia. El "mejor lector" del primer periodo (8 días, 45 peticiones)
  pedía la portada con `?cb=<timestamp>` para saltar caché;
- **cache-buster** — `?cb=`, `?_=`, `?rnd=` con valor numérico.

## Lectura = contenido, no portada

`es_profundo` solo es 1 para contenido real del observatorio
(`/research.html`, `/glosario.html`, `/docs.html`, `/sobre.html`, `/api.html`,
`/operativa.html`, `/costes.html`, `/apoyo.html`, `/suscribirse.html`,
`/privacidad.html`, `/aviso-legal.html` y el permalink `/c/<id>`).

La portada **no** cuenta, igual que en el blog: landing-sí, posts-no. Sin esto,
en los primeros 15 días el 78 % de las "lecturas de contenido" (634 de 807) eran
el canario, no gente.

## Privacidad

Las IP de terceros son datos personales. En la base se guarda **solo el
seudónimo** `h-xxxxxxxx` = `sha256(salt|ip)`[:8]. El salt vive en
`data/accesos.salt` con permisos 600 y es lo que protege: un hash de una IPv4
sin salt secreto es reversible por fuerza bruta sobre un espacio de 4.000
millones.

La IP en claro solo se escribe con `--guardar-raw`, en la tabla `ip_raw`, que
está separada para poder borrarla entera sin tocar el histórico. Por defecto no
se guarda.

Las listas de Cloudflare no se conservan en la base: leerlas para clasificar ya
es un tratamiento que el usuario no pidió.

## Red de hosting: lista acotada a propósito

`DATACENTER_CIDRS` es una heurística, no un detector. No hay BBDD GeoIP/ASN ni
módulo `geoip2` en el servidor, y traer una exige clave de MaxMind o registro.
Lo no reconocido se reporta como **candidato**, nunca como humano probado.

Verificado contra las listas oficiales el 2026-09-27:

- Cloudflare: la lista del módulo es la de `cloudflare.com/ips-v4`, literal.
- AWS: contra `ip-ranges.amazonaws.com`. `18.128.0.0/9` **no** es de AWS (se
  quitó) y `52.88` es `/15`, no `/13`.
- `104.30.167.164` **no** es Cloudflare (no aparece en su lista oficial). Antes
  se afirmaba lo contrario; ahora queda como candidato sin evidencia.

Regla para ampliar la lista: **solo con datos y verificando contra la fuente
oficial del proveedor**.

## El `log_format` tiene una comilla de sobra

El formato global de nginx es:

```
... "$http_referer" "$http_user_agent"" host=$host
```

Con una comilla extra tras el User-Agent. Un parser que exija el cierre limpio
no lee **ninguna** línea del log: el primer backfill devolvió 0 sobre 9.011
peticiones reales. `LINE_RE` acaba en `"+` a propósito, y
`test_parse_line_formato_real` fija una línea literal del log para que esto no
vuelva a pasar en silencio.

Por el mismo motivo el cursor guarda `leidas` y `ok`: si un fichero que antes
daba filas pasa a dar cero, `ingest` avisa en vez de avanzar el cursor.

## Límite del histórico

Los logs locales cubren 14 días. La base conserva para siempre lo que se ha
leído, así que **desde el 27-09-2026 el histórico es completo**, pero lo
anterior no es recuperable del servidor. Cloudflare Analytics guarda bastante
más, pero en el plan actual devuelve agregados por día/país/ASN, no la lista de
IP que pedía un "daily list" de IPs humanas.
