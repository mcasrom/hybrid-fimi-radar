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
> señal que separa un clic de un rastreo. Los números honestos están en «De dónde
> viene la gente», más abajo (medidos el 2-oct sobre la base reindexada).
>
> **Segunda corrección (2-oct-2026): doble conteo en la ingesta.** Las cifras de
> la tabla de orígenes estaban infladas ~25 % porque el cursor de lectura estaba
> indexado por nombre de fichero y la rotación de nginx renombra el log sin
> cambiar su contenido. Base reindexada; los totales por día ahora cuadran
> exactamente con las líneas de nginx. Detalle en «Uso».

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

`ingest` es **idempotente**: el cursor está indexado por **inodo** (clave
primaria `cursor_log.ino`), con `offset` y `bytes` dentro de ese inodo. Se puede
lanzar cada hora sin duplicar nada.

> **Doble conteo corregido (2-oct-2026).** El cursor estaba indexado por
> `fichero`. nginx rota **renombrando** (`access.log` → `access.log.1`, mismo
> inodo) y luego **reutiliza** la ruta `access.log`: al releer el día entero con
> el nuevo nombre y volver a insertar con `ON CONFLICT(fichero)`, el día se
> contaba dos veces y la fila del inodo viejo además se sobrescribía.
> Medido contra nginx: 29-Sep 990 filas en la base frente a 762 reales (748
> únicas); 30-Sep 1.659 frente a 1.237; 1-Oct 248 frente a 835 (día a medio
> ingestar). Base reindexada el 2-oct: **11.392 peticiones = exactamente las
> 11.392 líneas `host=fimi…` de los 15 logs conservados**, día a día idéntico.
> Un `ingest` repetido añade solo lo nuevo. Regresión fija en
> `test_rotacion_no_duplicatea_el_dia` (renombrado + compresión `.gz`) y
> `test_migracion_rehace_el_cursor_con_clave_inodo`.
>
> Lección: una clave de cursor sobre algo **mutable** (una ruta) no es una
> clave. Y una migración de esquema necesita su propio test: la rama de
> migración no se ejercita en una instalación nueva, así que un `INSERT` mal
> escrito falló en producción con «9 values for 8 columns» y dejó la base vacía.

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
  de entrada con público real. En 18-Sep→02-Oct (base reindexada): **38
  aperturas** (20 IP).
- **crawlers de IA** — `GPTBot`, `OAI-SearchBot`, `CCBot`, `ClaudeBot`… indexan
  para sus modelos. En los mismos 15 días: **68 peticiones**. No son público.

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

**Medido 18-Sep→02-Oct-2026** (11.396 peticiones, base **reindexada** el 2-oct;
antes esta tabla salía con el doble conteo y daba cifras ~25 % más altas):

| Origen | Peticiones | IP |
|---|---:|---:|
| raíz de buscador (previsualizador/bot) | 59 | 54 |
| red social (Facebook móvil, Bluesky) | 2 | 2 |
| **orígenes externos** (personas de fuera, con referrer) | **2** | 2 |
| sitio propio (blog + landing, CTA) | 64 | 14 |
| asistentes de IA con alguien detrás | 38 | 20 |
| crawlers de IA | 68 | |
| conversiones (alta/confirmar/sugerir/clave) | 4 | |

Lectura: el volumen real de público externo es **mínimo pero no nulo** (2 clics
identificables en 14 días, 4 conversiones acumuladas, 38 aperturas de asistente
de IA con alguien detrás). Lo que no se sostiene, tras reindexar, es la
conclusión anterior de que «la búsqueda de marca funciona» con 16 clics desde 14
IP: al deduplicar, los clicks de buscador quedan casi todos como
previsualizadores/bots y los 2 orígenes externos son redes sociales. Búsqueda de
marca: **por medir con Search Console, no con el log**.

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

