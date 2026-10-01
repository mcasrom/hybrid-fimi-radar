# Ciclo social del radar FIMI

Cómo se publica un post del radar en redes, qué es automático y qué es manual,
y por qué el flujo es «pregunto y apruebo» y no «publico solo».

Última revisión: **1-oct-2026** (incidente «siempre falla»).

---

## 1. Resumen en una línea

El cron de **martes y jueves a las 07:15 UTC** genera un post del siguiente tema
en rotación con señal alta y lo **manda a Telegram con dos botones**. El dueño
pulsa ✅ o ❌. Si pulsa ✅, se publica en **Mastodon + Bluesky** automáticamente y
se le remite el **texto de X** para copiar y pegar. **X nunca se publica de forma
automática** (la API de X es de pago).

---

## 2. Piezas

| Pieza | Ruta | Función |
|---|---|---|
| Cron | `crontab` → `15 7 * * 2,4` | Dispara el ciclo (martes/jueves 07:15) |
| Wrapper | `scripts/radar_social.sh` | Pasa `RADAR_SOCIAL_MODO` a `borrador` o `auto` |
| Generador | `detection/social_rotacion.py` | Elige tema, redacta, notifica o publica |
| Bot | `detection/radar_bot.py` (PM2 `radar-fimi-bot`) | Atiende los botones ✅/❌ |
| Publicadores | `social-poster/publish_mastodon.py`, `publish_bluesky.py` | Publican de verdad |
| Watchdog | `detection/social_verificar.py` | 07:30: comprueba que todo sigue vivo |
| Estado | `data/rotacion_estado.json` | Último tema publicado + historial |
| Borrador | `social-poster/radar_<AAAAMMDD>_<tema>.md` | Copia del post (y texto para X) |
| Log | `logs/social_rotacion.log` (+ `radar_social_cron.log`) | Traza del ciclo |

---

## 3. Modos

`RADAR_SOCIAL_MODO` decide qué hace el wrapper:

- **`borrador`** (el que usan los martes/jueves): genera el post, lo manda a
  Telegram con botones y **no publica nada**. Es el modo de producción.
- **`auto`**: publica sin preguntar. Se usa para pruebas o para un post puntual.

```bash
# producción: preguntar y esperar aprobación
RADAR_SOCIAL_MODO=borrador /home/deploy/scripts/radar_social.sh

# publicar un tema concreto ahora (X manual después)
.venv/bin/python detection/social_rotacion.py --tema defensa_espana --publicar --forzar
```

---

## 4. Flags de `social_rotacion.py`

| Flag | Efecto |
|---|---|
| *(ninguno)* | Borrador + notificación con botones. No publica |
| `--publicar` | Publica en Mastodon + Bluesky |
| `--forzar` | Salta el candado diario (úsalo al **aprobar** un borrador: la aprobación *es* la autorización) |
| `--tema X` | Fuerza un tema |
| `--dry` | Imprime, no escribe nada |

---

## 5. Reglas de seguridad

1. **Candado diario**: si hoy ya se publicó, no se repite (salvo `--forzar`).
   Evita duplicados si coinciden el cron y una tirada manual.
2. **Los dos canales o ninguno**: solo se marca como publicado si sale bien
   **Mastodon Y Bluesky**. Un fallo parcial no avanza la rotación.
3. **El botón ✅ verifica**: comprueba la marca real de publicación antes de
   decir «✅ Publicado».
4. **Silencio es una decisión**: si ningún tema tiene cluster ≥60, no se publica
   nada y se registra `[silencio]`.

---

## 6. Por qué el diseño es «pregunto y apruebo»

- **X es manual siempre**: la API de X es de pago y no se paga. El bot no publica
  en X; solo entrega el texto.
- **Mastodon y Bluesky son automáticos tras tu ✅**: sus APIs son gratuitas y ya
  funcionaban. Pedir approval evita publicar un post con una cifra que no cuadra.
- **Auditable**: si no se publica, es porque nadie aprobó. Antes de oct-2026 el
  log no decía ni si el mensaje de Telegram había salido, y eso hacía imposible
  distinguir «no se publicó» de «no llegó».

---

## 7. Watchdog (07:30)

`detection/social_verificar.py` corre 15 minutos después del cron y comprueba:

- que la rotación dejó rastro en el log de hoy;
- que hay publicación o, si no, un borrador pendiente de aprobar;
- que `radar-fimi-bot` está **online** (si no, los botones no responderán).

Si algo falla, avisa por Telegram con `sendMessage` (que no depende del
long-poll, así que llega aunque el bot esté caído). Log: `logs/social_verificar.log`.

```bash
.venv/bin/python detection/social_verificar.py          # estado de hoy
.venv/bin/python detection/social_verificar.py --fecha 20261006   # simular
```

---

## 8. Incidente «siempre falla» (1-oct-2026)

**Síntoma:** los posts de los martes/jueves nunca salían; había que recordarlo.

**No era un fallo de ejecución, era diseño.** Evidencia en los 5 logs del
histórico: `5/5` terminarían en `[borrador] no publicado`, sin un solo error. El
cron llevaba `RADAR_SOCIAL_MODO=borrador` escrito a mano y nunca pedía
`--publicar`, así que el camino de publicación automática no se ejecutaba jamás.
El botón ✅ era la única vía, y el log del bot tenía **0** pulsaciones.

**Defectos encontrados y corregidos (commit `1051307` y `e88f266`):**

1. El cron no llamaba a `--publicar` → se arregló la variable de modo.
2. El log del cron no redirigía salida → ahora a `logs/radar_social_cron.log`.
3. El botón ✅ llamaba a `--publicar` **sin `--forzar`** → el candado cortaba la
   publicación y el bot respondía «✅ Publicado» sin publicar. Añadido `--forzar`.
4. El botón ✅ decía «✅ Publicado» solo por `returncode == 0` → ahora exige la
   marca real de publicación.
5. El bot no registraba los callbacks y el envío a Telegram no logueaba los
   aciertos → ambos con traza (un fallo de entrega antes era invisible).
6. `_cargar_temas_activos()` ignoraba `estado` y ofrecía **3 temas cerrados**
   para suscribirse → ahora solo temas vivos.

**Cómo no volver a Repetirlo:** el watchdog de 07:30 avisa si el ciclo no dejó
borrador, si no se publicó, o si el bot está caído. Un martes «que no aparece»
ahora genera un aviso, no un silencio.

---

## 9. Recetas

```bash
# Estado del ciclo
.venv/bin/python detection/social_rotacion.py --dry

# Publicar un tema concreto ya (Mastodon+Bluesky), saltando el candado
.venv/bin/python detection/social_rotacion.py --tema defensa_espana --publicar --forzar

# Bot
pm2 restart radar-fimi-bot --update-env
pm2 describe radar-fimi-bot | grep -E "status|restarts"

# Verificación tras un martes/jueves
.venv/bin/python detection/social_verificar.py
tail -40 logs/social_rotacion.log
tail -20 logs/social_verificar.log
tail -20 /home/deploy/.pm2/logs/radar-fimi-bot-out.log
```
