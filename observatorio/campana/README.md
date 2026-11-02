# Observatorio de campaña 29N

Página pública: `https://fimi.viajeinteligencia.com/observatorio/campana/`.

## Regenerar

```bash
cd /home/deploy/hybrid-fimi-radar
python3 observatorio/campana/gen_campana.py
```

También se regenera desde `observatorio-static/run_static.sh` y se copia a `/var/www/fimi/observatorio/campana/index.html`. Para pruebas reproducibles:

```bash
python3 observatorio/campana/gen_campana.py --today 2026-11-02
```

## Estado dinámico

La página calcula el estado con la fecha de ejecución:

- **Precampaña:** días hasta el 13-nov.
- **Campaña:** día de campaña y días hasta el 29N.
- **Reflexión:** 28-nov.
- **Jornada electoral:** 29-nov.
- **Postelectoral:** constitución de las Cámaras, 23-dic.

No se muestran actos inventados: si no hay actos documentados, dice **0 actos documentados**.

## Datos

- `data/escanos_2026.json` y `data/censo_2026.json`: datos oficiales de contexto.
- `../calendario/calendario_oficial.json`: hitos del BOE, RD 806/2026.
- Fuente: BOE; INE, Oficina del Censo Electoral.
- Sondeos y media electoral: Observatorio 29N, separados de esta página.

## Límites

- Un hito oficial no es un acto de campaña.
- Una fecha prevista no es un acto celebrado.
- No se atribuyen actos, sedes, participantes ni posiciones sin fuente.
- No se publican pronósticos ni estimaciones propias de voto.
