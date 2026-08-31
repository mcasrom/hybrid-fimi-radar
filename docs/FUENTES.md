# Fuentes y palabras clave — European Hybrid & FIMI Radar

Todo se configura en `config.yaml`. Este documento es el inventario real (verificado 31/08/2026).

## Cómo añadir / eliminar

1. Editar `config.yaml`.
2. Para **añadir un feed**: añadir una entrada a la lista `feeds`:
   ```yaml
   feeds:
     - nombre: "Nombre visible"
       url: "https://.../feed/"
       tipo: media        # media | oficial | opendata
       pais: MA           # opcional: MA, DZ, MR, ES, etc.
   ```
3. Para **añadir palabras de búsqueda**: añadir a `keywords`:
   ```yaml
   keywords:
     - palabra: "Ceuta"
       plataformas: [bluesky, mastodon]   # donde se busca: bluesky | google-news | mastodon
   ```
4. Para **eliminar**: quitar la entrada. El cron 6h lo aplica en el siguiente ciclo.
5. Guardar y el cron lo recoge automáticamente (no hace falta reiniciar nada).

> Nota: para verificar que un feed responde, probar con:
> `python -c "import feedparser; print(len(feedparser.parse('URL').entries))"`

## Feeds RSS activos (13)

| # | Nombre | País | Tipo | URL |
|---|---|---|---|---|
| 1 | El Faro de Ceuta | ES (Ceuta) | media | https://elfarodeceuta.com/feed/ |
| 2 | Ceuta TV | ES (Ceuta) | media | https://ceutatv.com/feed/ |
| 3 | Melilla Hoy | ES (Melilla) | media | https://www.melillahoy.es/rss |
| 4 | El País España | ES | media | https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada |
| 5 | BBC Mundo | UK | media | https://feeds.bbci.co.uk/news/world/europe/rss.xml |
| 6 | Al Jazeera | QA | media | https://www.aljazeera.com/xml/rss/all.xml |
| 7 | El Mundo | ES | media | https://e00-elmundo.uecdn.es/elmundo/rss/portada.xml |
| 8 | MITECO embalses | ES | opendata | https://estadoembalses.es/api/embalses |
| 9 | Yabiladi Maroc (FR) | MA | media | https://www.yabiladi.com/rss/ |
| 10 | Algerie360 (FR) | DZ | media | https://www.algerie360.com/feed/ |
| 11 | Hespress Maroc (FR) | MA | media | https://fr.hespress.com/feed/ |
| 12 | TSA Algérie (FR) | DZ | media | https://www.tsa-algerie.com/feed/ |
| 13 | AMI Mauritanie (FR) | MR | oficial | https://fr.ami.mr/feed |

## Palabras clave activas (9)

| Palabra | Plataformas |
|---|---|
| Ceuta | bluesky, mastodon |
| Melilla | bluesky, mastodon |
| frontera Marruecos | bluesky |
| migración España | bluesky |
| Ceuta Melilla frontera | google-news |
| migración Canarias | google-news |
| España Marruecos | google-news |
| Ceuta | mastodon |
| migración | mastodon |

## Canales Telegram (2)

- `elfarodeceuta` (El Faro de Ceuta)
- `maldita_es` (Maldita, verificadores)

## Subreddits (2)

- `spain`
- `es`

## Fuentes probadas que NO funcionan (no usar)

- Interior España RSS — no expone RSS accesible
- ACNUR / UNHCR RSS — bloqueado / no RSS
- Frontex RSS — bloqueado / no RSS
- IOM/OMI RSS — no RSS
- El Pueblo de Ceuta, Melilla Media, La Voz de Melilla — feeds muertos
- TelQuel Maroc, Medias24, Le360 Maroc, Bladi.net — feeds muertos
- El Watan, Liberté Algérie, APS — feeds muertos
- Cridem, Le Calame (Mauritania) — feeds muertos
- RTVE, Europa Press — feeds devuelven 0

## Notas

- **Bluesky** se captura con la cuenta del operador (login autenticado), no requiere API de pago.
- **Mastodon** usa la API pública de `mastodon.social` (puede dar 429 si se abusa).
- **Reddit** usa RSS (`r/spain`, `r/es`); el endpoint JSON está bloqueado.
- Los feeds oficiales de organismos (ACNUR/Frontex/Interior) **no exponen RSS público** — se
  documenta como limitación, no se fuerza.
