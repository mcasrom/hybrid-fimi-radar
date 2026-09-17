# EIPD / DPIA ligera — Radar FIMI

> **Aviso**: este documento es una **evaluación interna y honesta** del tratamiento
> de datos del radar, no asesoramiento jurídico. Se publica para transparencia y
> para facilitar revisiones por terceros (EDMO, financiadores, investigadores).

## 1. Identificación

| | |
|---|---|
| **Tratamiento** | Radar FIMI (`fimi.viajeinteligencia.com`) |
| **Responsable** | Proyecto Radar FIMI (titular del ecosistema viajeinteligencia.com) |
| **Contacto** | `info-fimi@viajeinteligencia.com` |
| **Naturaleza** | Herramienta OSINT de análisis de **contenido público** |
| **Alojamiento** | Servidor propio en Hetzner (UE) |

## 2. Qué datos trata

El radar **solo recoge contenido público** de fuentes abiertas:

- **Fuentes**: RSS de medios, canales de Telegram públicos, subreddits, búsquedas
  públicas de Bluesky y Mastodon, Google News.
- **Campos almacenados** (`events`): `timestamp`, `source`, `title`, `url`, `text`,
  `language`, `author` (**handle público**), `tema_id`.
- **Derivados**: agrupaciones de cuentas (`cluster_events`), scores agregados
  (`assessments`) y hallazgos históricos (`findings`).
- **Suscripciones** (`suscripciones`): email o chat-id de Telegram, **con alta
  explícita** (doble opt-in en email).

**NO se tratan**: datos de cuentas privadas, mensajes privados, datos sensibles
(art. 9 RGPD), datos de menores por diseño, ni contenido tras *login*/muro de pago.

## 3. Finalidad y base jurídica

- **Finalidad**: detectar **coordinación, amplificación e inautenticidad** en la
  difusión de información pública (FIMI). Es análisis agregado, **no** perfilado
  individual ni toma de decisiones sobre personas.
- **Base jurídica**: interés legítimo (art. 6.1.f RGPD) en el análisis de información
  pública y datos manifiestamente públicos (art. 9.2.e, para las categorías
  especiales que pudieran aparecer incidentalmente en el texto citado).

## 4. Minimización y retención

- **Minimización**: se almacena el contenido estrictamente necesario para el análisis
  (texto, enlace, autor público, fecha). No se enriquece con datos personales de terceros.
- **Retención** (`detection/mantenimiento.py`, cron cada 6 h):
  - `events` y `findings`: **90 días** (purga + VACUUM).
  - `clusters`/`assessments`/`cluster_events`: se **reemplazan** cada ciclo (snapshot).
  - `suscripciones`: hasta la baja.
  - `bitacora`: registro de decisiones de gobernanza (sin datos personales).

## 5. Destinatarios y transferencias

- **No se venden ni ceden** datos a terceros.
- **Subencargados**: Hetzner (alojamiento, UE), Cloudflare (CDN/proxy) y Resend
  (envío de email) — estos dos últimos con posible acceso desde EE. UU.; se usan solo
  para servir la web y enviar el digest a quien se suscribe.
- La **API pública** (`/api/v1`) sirve solo datos **agregados** (scores, clusters), sin
  exportar handles individuales de forma masiva.

## 6. Derechos de las personas

Cualquier persona cuya **handle pública** aparezca en el corpus puede escribir a
`info-fimi@viajeinteligencia.com` para ejercer acceso, rectificación, supresión u
oposición. Al tratarse de contenido público y con retención de 90 días, la supresión
es efectiva de forma natural por la purga; las solicitudes explícitas se atienden.

## 7. Seguridad

- `.env` y `data/radar.db` con permisos **600**; acceso SSH por clave.
- HTTPS + HSTS; cabeceras `X-Frame-Options`, `nosniff`, `Referrer-Policy`,
  `Permissions-Policy` y CSP.
- `/api/` con *rate-limit* (20 req/min) y validación de parámetros.
- Backups cifrados-en-tránsito y rotados (4 copias + offsite semanal).

## 8. EIPD ligera — riesgos y mitigaciones

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| Reidentificación de una persona a partir de su handle público | Media | Bajo | Solo contenido público; sin perfilado individual; retención 90 d |
| Sesgo / falsos positivos que afecten a una cuenta | Media | Medio | Atribución **conservadora** (UNKNOWN por defecto); validación curada; disclaimers |
| Tratamiento incidental de categorías especiales en texto citado | Baja | Medio | Minimización; sin finalidad de perfilado; art. 9.2.e |
| Acceso no autorizado a la BD | Baja | Medio | Permisos 600; SSH por clave; sin exposición pública de la BD |
| Uso de los datos para fines distintos | Baja | Medio | Finalidad documentada; licencia AGPL; gobernanza pública |

## 9. Encaje con el AI Act (UE 2024/1689)

- El radar es principalmente **estadística clásica** (TF-IDF, grafos de coordinación,
  scoring determinista), **no** un modelo generativo ni un sistema de IA de propósito
  general.
- **No** realiza decisiones automatizadas con efectos jurídicos sobre personas
  (art. 22 RGPD) ni perfilado individual: agrupa **cuentas por comportamiento** y
  emite **señales agregadas**, con la ausencia de atribución como resultado válido.
- Por su finalidad (análisis de información pública, sin decisiones sobre personas),
  **no se identifica como sistema de alto riesgo** del anexo III. Se mantiene esta
  evaluación bajo revisión.

## 10. Limitaciones y compromisos

- El radar **mide coordinación, no autoría**: la atribución de actor es conservadora
  (UNKNOWN por defecto). Ver `docs/ATRIBUCION-LIMITACIONES.md`.
- **Ceguera de plataformas**: no cubre TikTok, X, Instagram ni WhatsApp (sin acceso
  público) → la ausencia de señal no implica ausencia de campaña.
- **Compromiso**: mantener la finalidad, la minimización y la transparencia; publicar
  los resultados de validación tal cual (incluidos los ceros).
