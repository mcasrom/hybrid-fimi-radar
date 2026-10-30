# Política de retención de datos

**Versión:** 2026-10-30  
**Ámbito:** Observatorio de lo publicado.

## 1. Titulares capturados

- **Caliente:** 90 días en `items`.
- **Histórico:** al superar 90 días pasan a `items_history`.
- **Histórico:** se conserva 2 años.
- **API y web:** por defecto solo consultan `items` (caliente).
- **Ejecución:** diaria a las 03:20 UTC; `observatorio/retention.py --apply`.
- **Dry-run:** por defecto, sin `--apply` no borra nada.

## 2. Fichas curadas

- Se conservan mientras exista el tema.
- No se borran por antigüedad.
- Cambios relevantes deben quedar fechados.

## 3. Salud de fuentes

- Se guarda el último estado por fuente.
- No se conserva un histórico completo de cada sonda.
- Los errores se registran en `ingest.log`.

## 4. Suscripciones

- Pendientes: se borran a los **30 días**.
- Confirmadas: mientras no haya baja.
- Bajas: el correo queda en lista de exclusión para no volver a escribir.
- Datos: correo, estado, fechas, página y UTM; sin IP ni cookies.

## 5. Logs y copias

- `ingest.log`: rotación operativa; no se publica.
- Copias de bases: según política del servidor; no se sirven públicamente.
- Los JSON públicos (`latest.json`, `feed_health.json`) solo contienen datos de publicación y fuentes.

## 6. Qué no se guarda

- No se guardan datos personales de los protagonistas de las noticias.
- No se guardan cookies de lectores.
- No se guardan credenciales en la base de datos.
