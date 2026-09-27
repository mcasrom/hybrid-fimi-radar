# Accesos al observatorio: humanos frente a máquinas

Registro histórico de quién entra en `fimi.viajeinteligencia.com`, separando
lectura humana de tráfico automatizado. Nace de un problema concreto: el log de
nginx rota a los 14 días y el informe diario era un texto que se enviaba y se
perdía, así que no había forma de responder "¿cuánta gente ha leído esto?".

> **Corrección importante (27-09-2026).** La primera versión tituló con
> `HUMANO_PROBABLE` sin mirar el referrer y llegó a decir "35 lectores humanos
> en 15 días". Era falso: casi todo era tráfico de previsualizadores y
> rastreadores. El titular correcto no son los pageviews sino **de dónde viene
> la gente** (`scripts/fimi_accesos.py origenes`), y el referrer es la única
> señal que separa un clic de un rastreo. Los números honestos de 13→27/Sep
> están en «De dónde viene la gente», más abajo.

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
.venv/bin/python scripts/fimi_accesos.py origenes             # de dónde viene la gente
.venv/bin/python scripts/fimi_accesos.py origenes --desde 2026-09-13
.venv/bin/python scripts/fimi_accesos.py reset --confirmar   # rebaca
```

`ingest` es **idempotente**: guarda un cursor por fichero `(inodo, offset)`, así
que se puede lanzar cada hora. Si rotó el log, el inodo cambia y se relee desde
el principio; los `.gz` ya completos se saltan.

## Las seis categorías

`INTERNAL` · `DUENO` · `API` · `BOT` · `ASISTENTE_IA` · `HUMANO_PROBABLE`

- **INTERNAL** — canario propio, healthchecks, monitor. Nunca es un lector.
  Incluye **las IPs del propio servidor, IPv4 e IPv6**: el canario y Uptime-Kuma
  salen por la IPv6 y `es_internal` solo miraba `127.0.0.0/8` y `::1/128`, así
  que cientos de peticiones de monitor propio entraban como "humano probable".
  La IPv6 observada está en `IPS_PROPIAS_EXTRA` (y se puede ampliar sin tocar
  código con `FIMI_IPS_PROPIAS`).
- **DUENO** — tu navegador. Humano, pero no es lectura: se cuenta aparte para no
  inflar la cifra titular.
- **API** — cualquier `/api/…`. Es una interfaz de máquinas aunque la pida una
  IP residencial. `/api.html` (la documentación) sí es de gente.
- **BOT** — crawler, escáner, 404, red de hosting, o un Chrome con la versión
  mal formada (un Chrome real manda cuatro componentes: `Chrome/120.0.0.0`, no
  `Chrome/120.0`). Incluye crawlers nombrados que antes se colaban como lectura
  recurrente: `SkyWatch`, `UnifiedPaths`, `NuxtFyi`, `FlipboardProxy`.
- **ASISTENTE_IA** — OpenAI, Anthropic, Perplexity, Google-Extended, CCBot…
  **Nunca se cuenta sin desglosar** (ver abajo): hay dos cosas mezcladas.
- **HUMANO_PROBABLE** — navegador, 200, IP que no es tuya ni una nube. **No es
  una persona probada**: es un candidato, y el daily separa los que sí leen.

### ASISTENTE_IA: gente y crawlers, siempre por separado

La categoría mezcla dos tráficos opuestos y sumarlos triplica el canal:

- **gente con alguien detrás** — `Claude-User`, `ChatGPT-User`,
  `Perplexity-User`: alguien preguntó a un asistente y el asistente vino a leer
  el enlace. No es un "lector" (lo descarga la máquina) pero sí es la única vía
  de entrada con público real. En 13→27/Sep: **23 aperturas** (11 IP).
- **crawlers de IA** — `GPTBot`, `OAI-SearchBot`, `CCBot`, `ClaudeBot`… indexan
  para sus modelos. En los mismos 15 días: **65 peticiones**. No son público.

`es_ia_gente()` separa las dos; el daily y la CLI informan de ambas.

## Lector vs. candidato

Un `GET /` no demuestra que haya alguien detrás. Solo cuenta como **LECTOR** si
abre contenido **y** vuelve:

- abrió contenido (`/research.html`, `/glosario.html`, `/c/<id>`, …) **y**
- repitió: `req ≥ 2` o apareció en `dias ≥ 2`.

Una sola página y un solo día **no es un lector**. En los datos reales ese
patrón era siempre un crawler: 9 IP distintas, todas con la misma UA de iOS 13
(diciembre de 2019) y una petición cada una, sin referer, recorriendo el
sitemap. Antes contaba como 9 lectores.

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

## De dónde viene la gente (el titular de verdad)

Los pageviews de "humano probable" no valen como titular: sin referrer, una
persona y un crawler que se disfraza son indistinguibles. El referrer se
**guardaba en el log y la ingesta lo tiraba**; ahora se persiste en
`accesos.referer` (con índice) y el daily titula por origen.

`clasificar_origen()` agrupa por tipo y aplica tres abstenciones deliberadas,
porque un referrer de plataforma NO es siempre una persona:

- **previsualizadores** — `l.facebook.com`, `telegram.org`, `slack.com`,
  `opengraph.io`, `embedly`… abren el enlace para enseñar la tarjeta. No se
  cuentan. En cambio `t.co` (clic desde X) o `m.facebook.com` SÍ son gente: la
  diferencia es el subdominio del que previsualiza.
- **raíz de buscador** — `https://www.google.com` sin ruta es un
  previsualizador; `google.com/search?q=…` es una búsqueda de verdad. Se
  distinguen mirando la ruta entera.
- **sitio propio** — `fimi.viajeinteligencia.com` navegando dentro de sí mismo
  (eran 2.035 peticiones y 69 IP) y los CTA desde el blog/landing se cuentan
  aparte, como "¿el blog alimenta al radar?", no como alcance ajeno.

**Medido 13→27/Sep-2026** (9.051 peticiones):

| Origen | Peticiones | IP |
|---|---:|---:|
| buscador (`google.com/search?q=viajeinteligencia`) | 16 | 14 |
| red social (Facebook móvil, Bluesky) | 2 | 2 |
| correo (app de Gmail) | 1 | 1 |
| **orígenes externos** | **19** | |
| sitio propio (blog + landing, CTA) | 20 | 13 |
| raíz de buscador (previsualizador) | 11 | 7 |
| asistentes de IA con alguien detrás | 23 | 11 |
| crawlers de IA | 65 | |
| conversiones (alta/confirmar/sugerir/clave) | 3 | |

Lectura: la **búsqueda de marca** funciona (16 clics de 14 IP distintas) y los
**asistentes** son una vía real (23), pero el volumen sigue siendo mínimo. Los
11 de "raíz de buscador" y los previsualizadores se dejan fuera a propósito.

### Trampa de conteo (corregida)

`origenes_del_dia()` devuelve `ips` como **conjunto**, no como entero. Antes se
metía el `COUNT(DISTINCT ip_pseudo)` por referer dentro de un set de enteros, así
que el recuento era "cuántas magnitudes distintas hay", no cuántas direcciones:
los 16 clics de Google desde 14 IP salían como **"1 IP"** y parecían un scraper.
Eran personas. `test_referer_se_guarda_y_llega_al_daily` lo fija.

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
leído, así que **desde el 27-09-2026 el histórico es completo e incremental**,
pero lo anterior no es recuperable del servidor.

Cloudflare Analytics guarda bastante más, y en teoría podría reconstruir el
tráfico anterior, pero **no está resuelto**:

- Con la clave global API actual, la API GraphQL **no responde**: `zone(zoneTag:)`
  da *unknown field*, `zones(filter:{accountTag:})` da *unknown arg* y
  `viewer { accounts { id } }` da *unknown field*. El esquema está restringido
  para ese token, así que no se ha podido ni comprobar qué devuelve.
- Documentado, el grouping por `clientIP` de `httpRequestsAdaptiveGroups`
  requiere Logpush, que es de pago. En planes habituales se obtienen agregados
  por día, país y ASN, **no la lista de IPs** que necesita un daily list de IPs
  humanas.

O sea: para tener "desde el inicio" harían falta los logs de origen, que
Cloudflare solo da con Logpush. Si en algún momento se contrata, el punto de
enganche es `ingestar()`: basta un `cf-backfill` que alimente la misma tabla
`accesos` con `fuente='cloudflare'`.

## Pendiente conocido

- `envio_informe_diario.py` y `monitor_lectores.py` (scripts del ecosistema)
  siguen con su propia lógica y su bug de lectura de `.gz`: solo miran hoy y
  ayer. Ahora FIMI tiene su propio registro, pero el del blog sigue así.

