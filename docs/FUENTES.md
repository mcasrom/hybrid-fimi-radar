# Fuentes y palabras clave — European Hybrid & FIMI Radar

Todo se configura en `config.yaml`. Este documento es el inventario real + notas de
fiabilidad editorial (**actualizado 14/09/2026**).

## Cómo añadir / eliminar

1. Editar `config.yaml`.
2. Para **añadir un feed RSS** (la metadata editorial es IMPORTANTE para la auditoría):
   ```yaml
   feeds:
     - nombre: "Nombre visible"
       url: "https://.../feed/"
       tipo: media        # media | oficial | analisis | osint | investigacion | opendata
       pais: MA           # opcional: MA, DZ, MR, ES, DE, SE, etc.
       bias: center-left  # OP -> least-biased | center | center-left | center-right | left | right | state
       reliability: mostly-factual  # OP -> high | mostly-factual | mixed
       transparency: medium         # OP -> high | medium | low
       factcheck_url: "https://mediabiasfactcheck.com/..."  # OP -> enlace MBFC
       idioma: es                   # es | fr | en | ar | de | sv
       note: "Contexto editorial breve donde sea útil."
   ```
   Los campos `bias/reliability/transparency` alimentan la card **"Salud y fiabilidad
   de las fuentes"** del dashboard y se usan para marcar fuentes a usar con cautela
   en el análisis FIMI. Investígalos (Media Bias/Fact Check, Ad Fontes, NewsGuard).
3. Para **añadir palabras de búsqueda**: añadir a `keywords` (ver sección abajo).
4. Para **eliminar**: quitar la entrada. El cron 6h lo aplica en el siguiente ciclo.
5. Guardar y el cron lo recoge automáticamente (no hace falta reiniciar nada).

## Resumen del catálogo (24/09/2026)

- **68 feeds RSS** · idiomas: **en 29 · fr 17 · es 14 · de 3 · sv 3 · ar 1 · ru 1**.
- **2 plataformas** de búsqueda (bluesky, google-news) · **3 canales Telegram** · **2 subreddits**.
- Metadata editorial (`bias`) presente por feed; `factcheck_url` formal en las fuentes con página MBFC.
- **Feeds con tema asignado** (pasan por el `filtro` del tema): **El Mundo Internacional →
  `espana_amenazas_hibridas`** (24/09), **EIA Today in Energy** y **Energy Monitor** → `energia`.
- **Nuevo (24/09)**: alta del feed **El Mundo · Internacional** + ampliación del tema
  `espana_amenazas_hibridas` (keywords/`filtro`: `ataque ruso`, `ataques rusos`, `ataque híbrido`,
  `ataques híbridos`, `drones rusos`, `gerbera`) para capturar la narrativa de amenaza híbrida rusa
  sobre España/Francia/Italia.
- *(Las tablas por sección de más abajo son del 14/09; pendientes de refresco total.)*

## Metadata editorial aplicada

Fechada en MBFC + Ad Fontes + valoración propia.

| Sesgo (bias) | N | Fuentes |
|---|---|---|
| least-biased (neutral) | 7 | BBC Mundo, Foreign Affairs, France 24, RFI France, Deutsche Welle (EN), Tagesschau (DE), SVT (SE) |
| center (centro) | 13 | El Faro de Ceuta, Ceuta TV, Melilla Hoy, Yabiladi, Hespress (FR/AR), Algerie360, Malijet, Koloni, Burkina24, La Nouvelle Tribune, OilPrice, El Periódico de la Energía, pv magazine |
| center-left (centro-izq) | 12 | El País, Al Jazeera, Le Monde Diplo, TSA, EUvsDisinfo, Bellingcat, MEE, EUobserver, Niger Report, Der Spiegel (DE), Dagens Nyheter (SE) |
| center-right (centro-der) | 3 | El Mundo, FAZ (DE), Svenska Dagbladet (SE) |
| left (izquierda) | 1 | The Intercept |
| state (estatal) | 4 | AMI Mauritanie, AIB Burkina, Sahel Horizon, RT en Español |

### Fiabilidad (reliability)
- **high (8)**: El País, Le Monde Diplo, Foreign Affairs, France 24, EUobserver, Deutsche Welle (EN), Tagesschau (DE), SVT (SE)
- **mostly-factual (27)**: mayoría
- **mixed (5)**: Al Jazeera, EUvsDisinfo, Hespress (AR), RT en Español, Sahel Horizon
- **low (0)**: ninguna

### Fuentes a usar con cautela en análisis FIMI
- **Al Jazeera** (reliability mixed, transparency low) — financiada por Qatar, sesgo
  pro-Palestina marcado en opinión.
- **EUvsDisinfo** (sesgo anti-derecha) — es la HERRAMIENTA oficial de la UE para detectar
  desinfo rusa, no una fuente neutra.
- **Middle East Eye** (transparency low) — vínculos con Qatar cuestionados (Wikipedia).
- **AMI Mauritanie / AIB Burkina** (state) — agencias oficiales, reflejan posición del gobierno.
- **Hespress (AR)** (mixed, transparency low) — medio marroquí líder en audiencia; medios
  argelinos lo acusan de sesgo pro-Rabat. Cotejar con Yabiladi / TSA Algérie.
- **RT en Español** (state, mixed) — estatal ruso sancionado por la UE (2022). Se vigila como
  **fuente de narrativas FIMI**, no como fuente fiable.
- **Sahel Horizon** (state, mixed) — narrativa pro-AES/soberanista vinculada al ecosistema
  African Initiative (Rusia). Vigilar como narrativa FIMI.

## Corroboration score (dinámico, automático)

`detection/health_fuentes.py` calcula para cada fuente el % de eventos corroborados por
>=1 evento de OTRA fuente en la misma ventana (±2h, 90d). Es un proxy de independencia:

- **Baja corroboration** (Bellingcat 60%, Le Monde Diplo 74%) = fuentes de análisis/OSINT
  que publican **investigaciones originales** sin paralelo de agencia — esperado, NO es
  bandera roja.
- **Alta corroboration** (breaking news al 95-100%) = noticias cubiertas en simultáneo por
  varias fuentes; válido pero menos "único".

Interpretación: una fuente con corroboration BAJA y además fiabilidad mixed/low desbloquea
alerta de precaución.

## Feeds RSS activos (40)

| # | Nombre | País | Tipo | Sesgo | Fiabilidad |
|---|---|---|---|---|---|
| 1 | El Faro de Ceuta | ES (Ceuta) | media | centro | mayormente factual |
| 2 | Ceuta TV | ES (Ceuta) | media | centro | mayormente factual |
| 3 | Melilla Hoy | ES (Melilla) | media | centro | mayormente factual |
| 4 | El País España | ES | media | centro-izq | alta |
| 5 | BBC Mundo | UK | media | neutral | mayormente factual |
| 6 | Al Jazeera | QA | media | centro-izq | mixta (aviso) |
| 7 | El Mundo | ES | media | centro-der | mayormente factual |
| 8 | Yabiladi Maroc (FR) | MA | media | centro | mayormente factual |
| 9 | Algerie360 (FR) | DZ | media | centro | mayormente factual |
| 10 | Hespress Maroc (FR) | MA | media | centro | mayormente factual |
| 11 | TSA Algérie (FR) | DZ | media | centro-izq | mayormente factual |
| 12 | AMI Mauritanie (FR) | MR | oficial | estatal | mayormente factual |
| 13 | Le Monde Diplomatique | FR | análisis | centro-izq | alta |
| 14 | Foreign Affairs | US | análisis | neutral | alta |
| 15 | RFI France | FR | media | neutral | mayormente factual |
| 16 | France 24 | FR | media | neutral | alta |
| 17 | EUvsDisinfo | BE | OSINT | centro-izq | mixta (aviso) |
| 18 | Bellingcat | NL | OSINT | centro-izq | mayormente factual |
| 19 | Middle East Eye | UK | media | centro-izq | mayormente factual (aviso transp.) |
| 20 | EUobserver | BE | media | centro-izq | alta |
| 21 | The Intercept | US | investigación | izquierda | mayormente factual |
| 22 | Hespress (AR) | MA | media | centro | mixta (aviso) |
| 23 | RT en Español | RU | media | estatal | mixta (aviso FIMI) |
| 24 | Deutsche Welle (EN) | DE | media | neutral | alta |
| 25 | Malijet (ML) | ML | media | centro | mayormente factual |
| 26 | Koloni (ML) | ML | media | centro | mayormente factual |
| 27 | Niger Report | NE | media | centro-izq | mayormente factual |
| 28 | Burkina24.com | BF | media | centro | mayormente factual |
| 29 | AIB - Agence Info Burkina | BF | oficial | estatal | mayormente factual |
| 30 | Sahel Horizon | — | media | estatal | mixta (aviso FIMI) |
| 31 | La Nouvelle Tribune | BJ | media | centro-izq | mayormente factual |
| 32 | OilPrice (EN) | — | media | centro | mayormente factual |
| 33 | El Periódico de la Energía (ES) | ES | media | centro | mayormente factual |
| 34 | pv magazine España (ES) | ES | media | centro | mayormente factual |
| 35 | Tagesschau (DE) | DE | media | neutral | alta |
| 36 | Der Spiegel (DE) | DE | media | centro-izq | mayormente factual |
| 37 | FAZ (DE) | DE | media | centro-der | mayormente factual |
| 38 | SVT Nyheter (SV) | SE | media | neutral | alta |
| 39 | Dagens Nyheter (SV) | SE | media | centro-izq | mayormente factual |
| 40 | Svenska Dagbladet (SV) | SE | media | centro-der | mayormente factual |

## Feeds de cobertura electoral — Alemania y Suecia (14/09/2026)

Añadidos para el capítulo **Election Threat Landscape** (elecciones de Alemania —Länder,
sep-2026— y Suecia —Riksdag, 13-sep-2026—). Se buscó **discurso doméstico** con balance
por país (público / centro-izq / centro-der). Todos verificados **HTTP 200 con UA de
navegador**:

- **Alemania**: Tagesschau (ARD, público), Der Spiegel (centro-izq), FAZ (centro-der).
- **Suecia**: SVT Nyheter (público), Dagens Nyheter (centro-izq), Svenska Dagbladet (centro-der).

**EEUU no añade feeds**: los midterms (nov-2026) se cubren con las keywords de `eeuu_politica`
+ feeds existentes (ES/FR/EN + RT). Motivo: los feeds son globales y sus eventos caen al
sumidero por defecto `frontera_sur`; meter prensa USA general ya ensució ese tema en una
prueba previa (iteración descartada). Se evita.

> **Regla vigente (Fase B)**: toda ampliación de feeds se mide antes de darla por buena —
> pico de memoria de `frontera_sur` (`/usr/bin/time -v`) contra el margen OOM (~3,4 GB).
> **Medición 14/09** con los 6 feeds nuevos (captura manual, 35.132 eventos): pico
> **2,51 GB** (**+0,05 GB** vs los 2,46 GB previos) → margen OOM intacto.

## Palabras clave activas

Bloque por tema (los `tema:` asignan el evento al tema; si no lleva `tema:`, es global):

- **Global** (tema ausente): Ceuta, Melilla, frontera Marruecos, migración España,
  Ceuta Melilla frontera, migración Canarias, España Marruecos, migración, Ceuta crise,
  frontière sud Europe, migration Maghreb, infiltration Ceuta, FIMI Europe,
  désinformation Russie Europe, inmigración irregular, propaganda rusa Magreb
- **geopolitica_ue_marruecos**: relaciones España Marruecos diplomacia, acuerdo bilateral
  España Marruecos, política exterior UE Magreb, Marruecos Unión Europea relaciones,
  accord Maroc Union européenne, diplomatie Maroc UE
- **politica_nacional** (producción): gobierno España oposición, partidos políticos España,
  congreso senado España, política España elecciones, crisis de gobierno
- **eeuu_politica** (producción): elecciones medio mandato EEUU 2026, interferencia electoral
  EEUU, desinformación elecciones EEUU, 2026 midterms interference
- **oriente_medio** (producción): Gaza, Gaza Israel, Iran, Houthi, Hutíes, Hormuz, Hezbollah,
  Hezbolá, Hamas, Hamás, Cisjordania, West Bank, Líbano Israel, Lebanon Israel
- **sahel** (piloto): Sahel, Mali, Burkina Faso, JNIM, yihadismo, Níger, AES Alianza de
  Estados del Sahel, Alliance des États du Sahel, djihadiste Sahel, yihadismo Sahel
- **energia** (piloto): petróleo, gas natural, Brent, OPEP, Sonatrach, Medgaz, gasoducto,
  precio de la luz, Ormuz, tarifa eléctrica

## Canales Telegram (4)

- `elfarodeceuta` (El Faro de Ceuta)
- `maldita_es` (Maldita, verificadores anti-desinfo)
- `burkinamaliniger` (Sahel)
- `sahelbrut` (Sahel)

## Subreddits (2)

- `spain`
- `es`

## Fuentes probadas que NO funcionan (no usar)

- Interior España RSS — no expone RSS accesible
- ACNUR / UNHCR RSS — bloqueado / no RSS
- Frontex RSS — bloqueado / no RSS
- IOM/OMI RSS — no RSS
- El Pueblo de Ceuta, Melilla Media, La Voz de Melilla — feeds muertos
- TelQuel Maroc, Medias24, Le360 Maroc, Bladi.net, Le Desk — feeds muertos / 403 Cloudflare
- El Watan, Liberté Algérie, APS — feeds muertos
- Cridem, Le Calame (Mauritania) — feeds muertos
- RTVE, Europa Press — feeds devuelven 0
- **Deutschlandfunk** (`deutschlandfunk.de/nachrichten.woch.html`) — 404 (14/09)
- **Politico** (`politico.com/rss/politicopicks.xml`) — 403 (14/09)
- **Omni (SE)** (`omni.se/rss`) — 404 (14/09)
- **Deutsche Welle DE** y **ZDF heute** — vivos, pero no añadidos (DW ya está en EN; se
  priorizó el balance público/centro-izq/centro-der por país)

## Notas

- **Bluesky** se captura con la cuenta del operador (login autenticado), no requiere API de pago.
- **Mastodon** usa la API pública de `mastodon.social` (puede dar 429 si se abusa).
- **Reddit** usa RSS (`r/spain`, `r/es`); el endpoint JSON está bloqueado.
- Los feeds oficiales de organismos (ACNUR/Frontex/Interior) **no exponen RSS público** — se
  documenta como limitación, no se fuerza.

## Nota: cabeceras marroquíes y Cloudflare (2026-09-04)

Verificado por el health monitor de fuentes: **Le Desk** (`https://ledesk.ma/feed/`) y otras
cabeceras marroquíes (Telquel, Medias24, L'Economiste, Maroc Hebdo, Le360) devuelven **403
Cloudflare** ("Just a moment", anti-bot JS) que el fetch del radar no puede saltar sin navegador
headless. **Cabeceras MA accesibles**: Yabiladi, Hespress (FR y AR).
