# Fuentes y palabras clave — European Hybrid & FIMI Radar

Todo se configura en `config.yaml`. Este documento es el inventario real + notas de
fiabilidad editorial (verificado 04/09/2026).

## Cómo añadir / eliminar

1. Editar `config.yaml`.
2. Para **añadir un feed RSS** (la metadata editorial es IMPORTANTE para la auditoría):
   ```yaml
   feeds:
     - nombre: "Nombre visible"
       url: "https://.../feed/"
       tipo: media        # media | oficial | analisis | osint | investigacion | opendata
       pais: MA           # opcional: MA, DZ, MR, ES, etc.
       bias: center-left  # OP -> least-biased | center | center-left | center-right | left | right | state
       reliability: mostly-factual  # OP -> high | mostly-factual | mixed
       transparency: medium         # OP -> high | medium | low
       factcheck_url: "https://mediabiasfactcheck.com/..."  # OP -> enlace MBFC
       note: "Contexto editorial breve donde sea útil."
   ```
   Los campos `bias/reliability/transparency` alimentan la card **"Salud y fiabilidad
   de las fuentes"** del dashboard y se usan para marcar fuentes a usar con cautela
   en el análisis FIMI. Investígalos (Media Bias/Fact Check, Ad Fontes, NewsGuard).
3. Para **añadir palabras de búsqueda**: añadir a `keywords` (ver sección abajo).
4. Para **eliminar**: quitar la entrada. El cron 6h lo aplica en el siguiente ciclo.
5. Guardar y el cron lo recoge automáticamente (no hace falta reiniciar nada).

## Metadata editorial aplicada (auditoría 2026-09-04)

Fechada en MBFC + Ad Fontes. 22 feeds, 22 con `bias`, 13 con `factcheck_url` formal.

| Sesgo (bias) | N | Fuentes |
|---|---|---|
| least-biased (neutral) | 5 | BBC Mundo, Foreign Affairs, France 24, RFI France (+1) |
| center (centro) | 6 | El Faro de Ceuta, Ceuta TV, Melilla Hoy, Yabiladi, Hespress, Le Desk |
| center-left (centro-izq) | 8 | El País, Al Jazeera, Le Monde Diplo, TSA, EUvsDisinfo, Bellingcat, MEE, EUobserver |
| center-right (centro-der) | 1 | El Mundo |
| left (izquierda) | 1 | The Intercept |
| state (estatal) | 1 | AMI Mauritanie |

### Fiabilidad (reliability)
- **high (5)**: El País, Le Monde Diplo, Foreign Affairs, France 24, EUobserver
- **mostly-factual (15)**: mayoría
- **mixed (2)**: Al Jazeera (MBFC: Left-Center, Mixed factual), EUvsDisinfo (proyecto
  EEAS/UE, contrarrelato ruso, sesgo anti-derecha según MBFC)
- **low (0)**: ninguna

### Fuentes a usar con cautela en análisis FIMI
- **Al Jazeera** (reliability mixed, transparency low) — financiada por Qatar, sesgo
  pro-Palestina marcado en opinión.
- **EUvsDisinfo** (sesgo anti-derecha) — es la HERRAMIENTA oficial de la UE para detectar
  desinfo rusa, no una fuente neutra.
- **Middle East Eye** (transparency low) — vínculos con Qatar cuestionados (Wikipedia).
- **AMI Mauritanie** (state) — agencia oficial MR, refleja posición del gobierno.

## Corroboration score (dinámico, automático)

`detection/health_fuentes.py` calcula para cada fuente el % de eventos corroborados por
>=-1 evento de OTRA fuente en la misma ventana (±2h, 90d). Es un proxy de independencia:

- **Baja corroboration** (Bellingcat 60%, Le Monde Diplo 74%) = fuentes de análisis/OSINT
  que publican **investigaciones originales** sin paralelo de agencia — esperado, NO es
  bandera roja.
- **Alta corroboration** (breaking news al 95-100%) = noticias cubiertas en simultáneo por
  varias fuentes; válido pero menos "único".

Interpretación: una fuente con corroboration BAJA y además fiabilidad mixed/low desbloquea
alerta de precaución.

## Feeds RSS activos

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
| 22 | Le Desk Marruecos | MA | media | centro | mayormente factual (403 CF) |

## Palabras clave activas

Bloque por tema (los `tema:` asignan el evento al tema; si no lleva `tema:`, es global):

- **Global** (tema ausente): Ceuta, Melilla, frontera Marruecos, migración España,
  Ceuta Melilla frontera, migración Canarias, España Marruecos, Ceuta, migración,
  Ceuta crise, frontière sud Europe, migration Maghreb, infiltration Ceuta,
  FIMI Europe, désinformation Russie Europe, inmigración irregular, propaganda rusa Magreb
- **geopolitica_ue_marruecos**: relaciones España Marruecos diplomacia, acuerdo bilateral
  España Marruecos, política exterior UE Magreb, Marruecos Unión Europea relaciones,
  Sahara occidental diplomacia, accord Maroc Union européenne, diplomatie Maroc UE
- **politica_nacional** (PILOTO): gobierno España oposición, partidos políticos España,
  congreso senado España, política España elecciones, crisis de gobierno

## Canales Telegram (2)

- `elfarodeceuta` (El Faro de Ceuta)
- `maldita_es` (Maldita, verificadores anti-desinfo)

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

## Nota: cabeceras marroquíes y Cloudflare (2026-09-04)
Verificado por el health monitor de fuentes: **Le Desk** (`https://ledesk.ma/feed/`) y otras
cabeceras marroquíes (Telquel, Medias24, L'Economiste, Maroc Hebdo, Le360) devuelven **403
Cloudflare** ("Just a moment", anti-bot JS) que el fetch del radar no puede saltar sin navegador
headless. Le Desk se MANTIENE en config como candidato futuro; mientras tanto aparecerá
"inactiva" en el health monitor (esperado). **Cabeceras MA accesibles**: Yabiladi y Hespress.