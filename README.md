# Observatorio de lo publicado

**Estado:** activo · software v0.1.0  
**Última actualización:** 30-oct-2026  
**Web:** https://fimi.viajeinteligencia.com/  
**API:** https://fimi.viajeinteligencia.com/observatorio/api/

## Qué es

Registro automático de titulares publicados sobre cuatro temas:

- **Frontera Sur** — España-Marruecos
- **Protestas juveniles**
- **Elecciones generales**
- **Infraestructuras España**

Captura cada **30 minutos** desde Google News RSS y **75 feeds directos** (España, Marruecos, Argelia, Francia, Reino Unido, Rusia y China). Cada entrada conserva medio, fecha y enlace.

## Qué no es

No confirma hechos, no atribuye intención ni responsabilidad y no usa clústeres, bandas o puntuaciones internas. Un titular es una publicación, no una verificación.

## FIMI antiguo

El FIMI anterior está **apagado**: su captura y sus servicios están detenidos. Su documentación queda archivada en [`docs/README-FIMI-ARCHIVO.md`](docs/README-FIMI-ARCHIVO.md). No es el producto activo.

## Documentación

- [`observatorio/README.md`](observatorio/README.md) — funcionamiento, fuentes y estado.
- [`observatorio/RETENCION.md`](observatorio/RETENCION.md) — retención de datos.
- [`observatorio/api/index.html`](observatorio/api/index.html) — API y exportación.
- [`observatorio/README.md`](observatorio/README.md) — cuatro temas y límites.

## Retención

Titulares: **90 días en caliente** y paso diario a histórico; histórico **2 años**. Fichas curadas: permanentes. Suscripciones: pendientes 30 días; confirmadas hasta la baja.

## DOI

El DOI del conjunto FIMI anterior sigue vivo: [10.5281/zenodo.23282710](https://doi.org/10.5281/zenodo.23282710). **No es el DOI del observatorio nuevo.**
