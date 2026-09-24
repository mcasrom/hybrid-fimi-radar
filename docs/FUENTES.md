# Fuentes y palabras clave — European Hybrid & FIMI Radar

Todo se configura en `config.yaml`. Este documento es el inventario real + notas de
fiabilidad editorial (**actualizado 24/09/2026**, generado desde `config.yaml`).

## Cómo añadir / eliminar

1. Editar `config.yaml`.
2. Para **añadir un feed RSS** (la metadata editorial es IMPORTANTE para la auditoría):
   ```yaml
   feeds:
     - nombre: "Nombre visible"
       url: "https://.../feed/"
       tipo: media        # media | oficial | analisis | osint | investigacion | opendata
       pais: MA           # opcional: MA, DZ, MR, ES, DE, SE, etc.
       bias: center-left  # least-biased | center | center-left | center-right | left | right | state
       reliability: mostly-factual  # high | mostly-factual | mixed
       transparency: medium         # high | medium | low
       factcheck_url: "https://mediabiasfactcheck.com/..."
       idioma: es                   # es | fr | en | ar | de | sv | ru
       note: "Contexto editorial breve donde sea útil."
       tema: energia      # OPCIONAL: pasa el feed por el filtro de ese tema
   ```
   Los campos `bias/reliability/transparency` alimentan la card **«Salud y fiabilidad
   de las fuentes»** del dashboard. Investígalos (MBFC, Ad Fontes, NewsGuard).
   **Asignar `tema` a un feed** lo hace pasar por el `filtro` del tema (útil para
   fuentes de un beat concreto; p.ej. `El Mundo Internacional → espana_amenazas_hibridas`).
3. Para **añadir palabras de búsqueda**: añadir a `keywords` (sección abajo).
4. Para **eliminar**: quitar la entrada. El cron 6h lo aplica en el siguiente ciclo.
5. Guardar y el cron lo recoge automáticamente (no hace falta reiniciar nada).

## Resumen del catálogo (24/09/2026)

- **68 feeds RSS** · idiomas: en 29 · fr 17 · es 14 · de 3 · sv 3 · ar 1 · ru 1
- **2 plataformas** de búsqueda (bluesky, google-news) · **3 canales Telegram** · **2 subreddits** (spain, es).
- **Feeds con `tema` asignado** (pasan por el `filtro` del tema): El Mundo Internacional → `espana_amenazas_hibridas` · EIA Today in Energy (EN) → `energia` · Energy Monitor (EN) → `energia`.
- **Novedad (24/09)**: alta de **El Mundo · Internacional** y ampliación del tema
  `espana_amenazas_hibridas` (keywords/`filtro`: `ataque ruso`, `ataques rusos`, `ataque híbrido`,
  `ataques híbridos`, `drones rusos`, `gerbera`) para la narrativa de amenaza híbrida rusa.

## Metadata editorial aplicada

Fechada en MBFC + Ad Fontes + valoración propia.

### Sesgo (bias)

| Sesgo | N | Fuentes |
|---|---|---|
| center | 29 | El Faro de Ceuta, Ceuta TV, Melilla Hoy, Yabiladi Maroc (FR), Algerie360 (FR), Hespress Maroc (FR), Hespress (AR), Malijet (ML), Koloni (ML), Burkina24.com, OilPrice (EN), El Periódico de la Energía (ES), pv magazine España (ES), Energy Monitor (EN), Carbon Brief (EN), Galaxia Militar (ES), Breaking Defense (EN), TechCrunch AI, Ars Technica, MIT Technology Review, AI News, Numerama, ActuIA, Xataka, The Verge AI, The Decoder, The Cyberwire, Recorded Future, IntelNews |
| center-left | 15 | El Pais Espana, Al Jazeera, TSA Algerie (FR), Le Monde Diplomatique, EUvsDisinfo, Bellingcat, Middle East Eye, EUobserver, Niger Report, La Nouvelle Tribune, Der Spiegel (DE), Dagens Nyheter (SV), El Pais Tecnologia, Wired AI, Politico EU |
| state | 11 | AMI Mauritanie (FR), RT en Español, AIB - Agence Info Burkina, Sahel Horizon, TASS (EN), RIA Novosti (RU), CGTN (EN), Global Times (EN), Sputnik Mundo, Meduza EN, The Insider |
| least-biased | 8 | BBC Mundo, Foreign Affairs, RFI France, France 24, Deutsche Welle (EN), EIA Today in Energy (EN), Tagesschau (DE), SVT Nyheter (SV) |
| center-right | 4 | El Mundo, El Mundo Internacional, FAZ (DE), Svenska Dagbladet (SV) |
| left | 1 | The Intercept |

### Fiabilidad (reliability)

- **mostly-factual (32)**: El Faro de Ceuta, Ceuta TV, Melilla Hoy, BBC Mundo, El Mundo, El Mundo Internacional, Yabiladi Maroc (FR), Algerie360 (FR), Hespress Maroc (FR), TSA Algerie (FR), AMI Mauritanie (FR), RFI France, EUvsDisinfo, Bellingcat, Middle East Eye, The Intercept, Malijet (ML), Koloni (ML), Niger Report, Burkina24.com, AIB - Agence Info Burkina, La Nouvelle Tribune, OilPrice (EN), El Periódico de la Energía (ES), pv magazine España (ES), Energy Monitor (EN), Galaxia Militar (ES), Breaking Defense (EN), Der Spiegel (DE), FAZ (DE), Dagens Nyheter (SV), Svenska Dagbladet (SV)
- **high (19)**: El Pais Espana, Le Monde Diplomatique, Foreign Affairs, France 24, EUobserver, Deutsche Welle (EN), EIA Today in Energy (EN), Carbon Brief (EN), Tagesschau (DE), SVT Nyheter (SV), TechCrunch AI, Ars Technica, MIT Technology Review, Numerama, Xataka, El Pais Tecnologia, The Verge AI, The Decoder, Wired AI
- **mixed (17)**: Al Jazeera, Hespress (AR), RT en Español, Sahel Horizon, TASS (EN), RIA Novosti (RU), CGTN (EN), Global Times (EN), AI News, ActuIA, Sputnik Mundo, Meduza EN, The Insider, Politico EU, The Cyberwire, Recorded Future, IntelNews

### Fuentes a usar con cautela en análisis FIMI
- **Estatales (state)**: `RT en Español`, `TASS`, `RIA Novosti`, `CGTN`, `Global Times`,
  `Sputnik Mundo`, `AMI Mauritanie`, `AIB Burkina`, `Sahel Horizon` — reflejan la posición
  de su gobierno; se vigilan como **fuente de narrativas FIMI**, no como fuente fiable.
- **Mixed / con matices**: `Al Jazeera` (financiación Qatar), `EUvsDisinfo` (herramienta
  oficial UE anti-desinfo rusa, no neutra), `Middle East Eye` (transparencia baja),
  `Hespress (AR)` (medio marroquí líder; cotejar con Yabiladi/TSA), `Politico EU`,
  `The Cyberwire`, `Recorded Future`, `IntelNews` (inteligencia privada/OSINT),
  `Meduza EN`, `The Insider` (medios rusos en el exilio, línea anti-Kremlin).
- Cotejar siempre con fuentes `high`/`least-biased` del catálogo.

## Corroboration score (dinámico, automático)

`detection/health_fuentes.py` calcula para cada fuente el % de eventos corroborados por
≥1 evento de OTRA fuente en la misma ventana (±2h, 90d). Es un proxy de independencia:

- **Baja corroboration** = fuentes de análisis/OSINT que publican **investigaciones
  originales** sin paralelo de agencia — esperado, **no** es bandera roja.
- **Alta corroboration** (breaking news ~95-100%) = cubierto en simultáneo por varias
  fuentes; válido pero menos «único».

Una fuente con corroboration BAJA y además fiabilidad `mixed`/`low` desbloquea alerta de precaución.

## Feeds RSS activos

| # | Nombre | País | Tipo | Sesgo | Fiabilidad | Idioma | Tema |
|---|---|---|---|---|---|---|---|
| 1 | EIA Today in Energy (EN) | — | media | least-biased | high | en | energia |
| 2 | Energy Monitor (EN) | — | media | center | mostly-factual | en | energia |
| 3 | El Mundo Internacional | — | media | center-right | mostly-factual | es | espana_amenazas_hibridas |
| 4 | ActuIA | FR | media | center | mixed | fr | — |
| 5 | AI News | GB | media | center | mixed | en | — |
| 6 | AIB - Agence Info Burkina | BF | oficial | state | mostly-factual | fr | — |
| 7 | Al Jazeera | — | media | center-left | mixed | en | — |
| 8 | Algerie360 (FR) | DZ | media | center | mostly-factual | fr | — |
| 9 | AMI Mauritanie (FR) | MR | oficial | state | mostly-factual | fr | — |
| 10 | Ars Technica | US | media | center | high | en | — |
| 11 | BBC Mundo | — | media | least-biased | mostly-factual | es | — |
| 12 | Bellingcat | — | osint | center-left | mostly-factual | en | — |
| 13 | Breaking Defense (EN) | — | media | center | mostly-factual | en | — |
| 14 | Burkina24.com | BF | media | center | mostly-factual | fr | — |
| 15 | Carbon Brief (EN) | — | media | center | high | en | — |
| 16 | Ceuta TV | — | official | center | mostly-factual | es | — |
| 17 | CGTN (EN) | CN | media | state | mixed | en | — |
| 18 | Dagens Nyheter (SV) | SE | media | center-left | mostly-factual | sv | — |
| 19 | Der Spiegel (DE) | DE | media | center-left | mostly-factual | de | — |
| 20 | Deutsche Welle (EN) | — | media | least-biased | high | en | — |
| 21 | El Faro de Ceuta | — | official | center | mostly-factual | es | — |
| 22 | El Mundo | — | media | center-right | mostly-factual | es | — |
| 23 | El Pais Espana | — | media | center-left | high | es | — |
| 24 | El Pais Tecnologia | ES | media | center-left | high | es | — |
| 25 | El Periódico de la Energía (ES) | — | media | center | mostly-factual | es | — |
| 26 | EUobserver | — | media | center-left | high | en | — |
| 27 | EUvsDisinfo | — | osint | center-left | mostly-factual | en | — |
| 28 | FAZ (DE) | DE | media | center-right | mostly-factual | de | — |
| 29 | Foreign Affairs | — | analisis | least-biased | high | en | — |
| 30 | France 24 | — | media | least-biased | high | fr | — |
| 31 | Galaxia Militar (ES) | — | media | center | mostly-factual | es | — |
| 32 | Global Times (EN) | CN | media | state | mixed | en | — |
| 33 | Hespress (AR) | MA | media | center | mixed | ar | — |
| 34 | Hespress Maroc (FR) | MA | media | center | mostly-factual | fr | — |
| 35 | IntelNews | US | rss | center | mixed | en | — |
| 36 | Koloni (ML) | ML | media | center | mostly-factual | fr | — |
| 37 | La Nouvelle Tribune | — | media | center-left | mostly-factual | fr | — |
| 38 | Le Monde Diplomatique | — | analisis | center-left | high | fr | — |
| 39 | Malijet (ML) | ML | media | center | mostly-factual | fr | — |
| 40 | Meduza EN | RU | rss | state | mixed | en | — |
| 41 | Melilla Hoy | — | official | center | mostly-factual | es | — |
| 42 | Middle East Eye | — | media | center-left | mostly-factual | en | — |
| 43 | MIT Technology Review | US | media | center | high | en | — |
| 44 | Niger Report | NE | media | center-left | mostly-factual | fr | — |
| 45 | Numerama | FR | media | center | high | fr | — |
| 46 | OilPrice (EN) | — | media | center | mostly-factual | en | — |
| 47 | Politico EU | EU | rss | center-left | mixed | en | — |
| 48 | pv magazine España (ES) | — | media | center | mostly-factual | es | — |
| 49 | Recorded Future | US | rss | center | mixed | en | — |
| 50 | RFI France | — | media | least-biased | mostly-factual | fr | — |
| 51 | RIA Novosti (RU) | RU | media | state | mixed | ru | — |
| 52 | RT en Español | — | media | state | mixed | es | — |
| 53 | Sahel Horizon | — | media | state | mixed | fr | — |
| 54 | Sputnik Mundo | RU | media | state | mixed | es | — |
| 55 | Svenska Dagbladet (SV) | SE | media | center-right | mostly-factual | sv | — |
| 56 | SVT Nyheter (SV) | SE | media | least-biased | high | sv | — |
| 57 | Tagesschau (DE) | DE | media | least-biased | high | de | — |
| 58 | TASS (EN) | RU | media | state | mixed | en | — |
| 59 | TechCrunch AI | US | media | center | high | en | — |
| 60 | The Cyberwire | US | rss | center | mixed | en | — |
| 61 | The Decoder | DE | media | center | high | en | — |
| 62 | The Insider | RU | rss | state | mixed | en | — |
| 63 | The Intercept | — | investigacion | left | mostly-factual | en | — |
| 64 | The Verge AI | US | media | center | high | en | — |
| 65 | TSA Algerie (FR) | DZ | media | center-left | mostly-factual | fr | — |
| 66 | Wired AI | US | media | center-left | high | en | — |
| 67 | Xataka | ES | media | center | high | es | — |
| 68 | Yabiladi Maroc (FR) | MA | media | center | mostly-factual | fr | — |

## Palabras clave activas

Bloque global `keywords:` agrupado por tema (el campo `tema:` asigna el evento; sin él, `frontera_sur`):

- **defensa_espana** (11): fuerzas armadas, Eurofighter, Ministerio de Defensa, JEMAD, ejército español, industria de defensa, industria militar, gasto en defensa, presupuesto de defensa, submarino S-80, fragata
- **eeuu_politica** (4): elecciones medio mandato EEUU 2026, election interference, desinformación elecciones EEUU, 2026 midterms interference
- **elecciones** (31): elecciones, electoral, campaña electoral, urnas, papeletas, fraude electoral, afd, midterms, medio mandato, election interference, sondeos, votantes, landtagswahl, bundestagswahl, europawahl, wahlkampf, wahlen, wähler, riksdag, riksdagsval, valet, väljare, rösta, valrörelse, выборы, госдума, vēlēšanas, saeima, izbori, eleições, избори
- **energia** (10): petróleo, gas natural, Brent, OPEP, Sonatrach, Medgaz, gasoducto, precio de la luz, Ormuz, tarifa eléctrica
- **espana_amenazas_hibridas** (22): desinformación, propaganda, injerencia, espionaje, ciberataque, sabotaje, guerra híbrida, amenaza híbrida, desinformaciones, propagandas, injerencias, espionajes, ciberataques, sabotajes, guerras híbridas, amenazas híbridas, ataque ruso, ataques rusos, ataque híbrido, ataques híbridos, drones rusos, gerbera
- **frontera_sur** (13): Ceuta, Melilla, frontera Marruecos, migración España, Ceuta Melilla frontera, migración Canarias, España Marruecos, migración, Ceuta crise, Maghreb, infiltration, inmigración irregular, soldados fantasma
- **geopolitica_ue_marruecos** (4): relaciones España Marruecos diplomacia, acuerdo bilateral España Marruecos, política exterior UE Magreb, Marruecos Unión Europea relaciones
- **inteligencia_artificial** (11): inteligencia artificial, artificial intelligence, OpenAI, ChatGPT, Gemini, Claude, Anthropic, deepfake, Nvidia, robot, algoritmo
- **oriente_medio** (14): Gaza, Gaza Israel, Iran, Houthi, Hutíes, Hormuz, Hezbollah, Hezbolá, Hamas, Hamás, Cisjordania, West Bank, Líbano Israel, Lebanon Israel
- **politica_nacional** (8): gobierno España oposición, partidos políticos España, congreso senado España, política España elecciones, crisis de gobierno, fuerzas armadas, JEMAD, Ministerio de Defensa
- **sahel** (8): Sahel, Mali, Burkina Faso, JNIM, yihadismo, Níger, AES, djihadiste

## Canales Telegram

- `elfarodeceuta`
- `maldita_es`
- `sahelbrut`

## Subreddits

- `spain`
- `es`

## Fuentes probadas que NO funcionan (no usar)

- Interior España / ACNUR-UNHCR / Frontex / IOM — no exponen RSS público.
- El Pueblo de Ceuta, Melilla Media, La Voz de Melilla — feeds muertos.
- TelQuel, Medias24, Le360, Bladi.net, Le Desk, L'Economiste, Maroc Hebdo — 403 Cloudflare / muertos.
- El Watan, Liberté Algérie, APS — feeds muertos.
- Cridem, Le Calame (Mauritania) — feeds muertos.
- RTVE, Europa Press — devuelven 0.
- Deutschlandfunk (404), Politico.com/politicopicks (403), Omni SE (404).
- Deutsche Welle DE y ZDF heute — vivos pero no añadidos (DW ya en EN).

## Notas

- **Bluesky** se captura con la cuenta del operador (login autenticado), sin API de pago.
- **Mastodon** usa la API pública de `mastodon.social` (puede dar 429 si se abusa).
- **Reddit** usa RSS (`r/spain`, `r/es`); el endpoint JSON está bloqueado.
- **Los RSS/medios NO entran al grafo de coordinación** (solo `bsky/tg/reddit/masto`):
  aportan cobertura/eco («narrativa amplificada»), no clusters.
- Cabeceras marroquíes (Le Desk, Telquel, Medias24, Le360…) devuelven **403 Cloudflare**;
  accesibles: **Yabiladi** y **Hespress (FR/AR)**.
