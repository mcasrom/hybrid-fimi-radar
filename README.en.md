# Amplification observatory (FIMI domain)

*English · [Español](README.md)*

## 1. What it is

**Amplification observatory:** an OSINT system that measures, from
public data, **patterns of amplification** —synchronisation, content repetition and
structural clustering— across social platforms and the press around a set of topics
(southern border & Morocco, Middle East, elections, energy, AI, Sahel, defence and hybrid
threats…). It looks at **who pushes the same message, at the same time and in the same
way**, and publishes it as **measured amplification**. A high band does **not** equal
coordination: in the blind validation of 29/Sep/2026 only **3 of 40** high-band cases
(8.3%) showed coordination. FIMI is the **domain** being observed, not a detection: the
observatory **does not** confirm campaigns or attribute actors.

The tool **does not attribute an actor or confirm inauthenticity or a foreign campaign
by itself**: its outputs should be interpreted as **behavioural signals requiring
additional validation, contextual analysis, and organisational evidence**. It doesn't
fact-check "true or false". It's meant for journalists, researchers and citizens who
want to check the data themselves.

## 2. What it does NOT do

- **It is not a FIMI detector.** It does not prove a campaign exists: it produces
  **candidates for investigation**. HIGH/CRITICAL clusters carry **plausible alternative
  explanations** —often more parsimonious—: mainstream echo, organic virality, legitimate
  coordinated activism, non-malicious automation or graph artefacts. Claiming "confirmed
  FIMI" requires **independent external evidence**.
- **No authorship or intent attribution.** Attribution is a separate, conservative module:
  the default result is `UNKNOWN`. The radar never claims "this is Russia/China/Morocco/
  the US/the left/the right".
- **No ideology scoring**: an opinion is never treated as a threat.
- **It describes patterns, not intentions.** It measures form (synchronisation, repeated
  links, recurrence), not motive.
- **It does not point at people.** The radar **does surface the public handles** of the
  accounts that make up a cluster (they are the evidence of coordination), but it **does not
  profile anyone**: it does not infer personal data, judge individuals, or present them as
  guilty. A cluster describes collective behaviour, not an accusation.
- **It doesn't decide.** It flags and suggests (promote/close a topic); the call is always
  human.

## 3. How it works (conceptually)

Every 6 h it captures public posts (Bluesky, Telegram, Reddit, Mastodon, Google News, RSS),
normalises them and computes structural components per account **cluster**:

- **Synchronisation (coordination):** how closely posts line up in time.
- **Anomaly:** how far these accounts' behaviour deviates from normal (outlier detection,
  with no prior knowledge of the account).
- **Infrastructure:** links/domains shared across accounts.
- **Content similarity** and **amplification** (a global signal of the cycle).

> **Network density** is still computed and published as a datum, but it **does not
> weight the score**: it is a transform of the same coordination axis (double counting)
> and was removed on 24-Sep-2026. It feeds the attribution module (hypothesis H3).

Each cluster also publishes **`alternative_explanations`**: alternative explanations with a
status (`supported` / `plausible` / `ruled_out`) and the **evidence** behind it. Among others,
it separates two situations that **must not be confused**:

- **`single_source_feed`** — a single **account or domain concentrates almost everything**
  (e.g. someone posting their own site). Not coordination between distinct accounts → **low
  priority**.
- **`cross_account_synchrony`** — **several distinct accounts, none dominant, with the same
  content**. This is the pattern that **does deserve human review** → **high priority**.

Plus mainstream echo, single-piece echo, organic virality, synchronisation without an operator,
non-malicious automation, legitimate mobilisation, graph artefact, **text repeated across accounts**
(`copypasta_textual`, 5-Oct: same or near-identical simhash text across distinct accounts in a burst)
and *no conclusive explanation*. It is not a "truth" classifier: it is material for human review, shown in the
dashboard, the API and the exports.

Each cluster also publishes a **narrative role** (`narrative_subtype`) separating *talking about
FIMI* — `official_response`, `incident_report`, `meta_analysis` — from *possible FIMI narrative*
(`potential_narrative`, `coordination_signal`). It helps avoid reading as an "operation" what is
really a story that counters or analyses it.

From these it produces a **0–100 score** and a **band** (NORMAL→CRITICAL), and evaluates
**alternative hypotheses** (anti-confirmation-bias):

H1 organic viral · H2 structured domestic coordinated campaign ·
**H2b synchronised activity without operator attribution** · H3 foreign influence operation ·
H4 media amplification · H5 sustained synchronisation with diverse content (no structure) ·
H6 no conclusive evidence.

Hypotheses **do not change the score**; they are an informational reading.

### Auditing high signals (HIGH/CRITICAL)

So that every high signal can be reviewed **without claiming it is FIMI**, `detection/auditoria_high.py`
produces an auditable record for each cluster with score ≥60: accounts, events, distinct URLs/domains,
time window, components, k-core, **narrative role** and **alternative explanations**, plus the
**chain** that separates *observable coordination* (measured) from *inauthenticity*, *intent* and
*foreign dimension* (which the radar cannot confirm on its own) and from *confirmed FIMI* (which needs
independent evidence). It orders human review by priority.

It is **read-only and lightweight**: it audits only clusters ≥ threshold and their events, with
configurable limits (`auditoria` in `config.yaml`: max clusters, events and text length, timeout,
seed). No network, LLMs or heavy dependencies.

```bash
python detection/auditoria_high.py --formato csv --out auditoria_high.csv
python detection/auditoria_high.py --tema <topic> --limite 50
python detection/auditoria_high.py --formato blind --muestra 40 --seed 7 --out blind.csv
```

In `--formato blind` sampling is **always** applied (with `--muestra`/`--seed`; if you omit
`--muestra`, **40 rows** are used by default, `auditoria.blind_default_muestra`). The blind CSV
does **not** include narrative role, main explanation, priority, hypotheses or attribution: only
raw evidence and components (accounts, events, URLs/domains, window, k-core, evidence texts and
URLs) plus the empty `label_*` columns for human annotation.

## 4. Current status

Latest run snapshot (27 Sep 2026, **v0.2**; figures grow every cycle — the dashboard shows
the live value):

- **8 active topics** (6 in production + 2 pilot: `elecciones`, `defensa_espana`).
  `espana_amenazas_hibridas` was merged into `defensa_espana` on 27 Sep (renamed "Spain — defence and hybrid threats").
- **~133,000 events** and **933 clusters** (90-day window).
- **78 RSS feeds** (5 Spanish ones with `tema: espana_elecciones` since 5 Oct + `Meneame Portada` since 7 Oct, no tema: the gate decides) + 2 platform searches, 6 public Telegram channels (2 parked), subreddits parked (429).
- Live dashboard: https://fimi.viajeinteligencia.com · read-only API v1: `/api/v1/…`.
- **Open datasets by topic** (5-Oct): `/datos/<tema>/clusters.{csv,json}` per cluster
  (no texts or authors) + `datapackage.json` (CC BY 4.0) + freshness `status.json`.
- **Contrast-checked possible hoaxes** (5-Oct, expanded 6-Oct): crosses high/anomalous-band clusters
  with recent **fact-checker** pieces (Maldita/Newtral, 14 d). Offered as a **KPI mini-card** on the
  dashboard (after the topic cards), **RSS feed** (`/datos/bulos.xml`) and **JSON** (`/datos/bulos.json`)
  under the **"Bulos ▾"** nav menu, plus a **social card** `/bulos-og.png`. **Contrast, not verdict**:
  it attributes no actor and confirms no hoax.
- **60-day observation window** (6-Oct): the pipeline only sees events from the last 60 d
  (`run_fimi --ventana-dias`; measured neutral across all 9 topics); old signals expire.
  Storage keeps 90 d (`mantenimiento.py`).
- **API for journalists** (6-Oct): daily series per topic (`/api/v1/tema/<slug>/serie?dias=30`,
  aggregates only) and cluster search (`/api/v1/buscar?q=&tema=&limite=`, redacted snippets,
  no authors). Documented in `/api.html` and the OpenAPI spec.
- **Sitemap with `/casos/electoral/`** (6-Oct, 15 URLs) + `/api/v1/openapi.json` served after
  an nginx exception (the extension rule swallowed it → 404 before).
- Latest release: **v0.2**.

## 5. Known limitations

- **Structural attribution only:** no organisational evidence is queried (beyond a weak
  RDAP domain signal). `UNKNOWN` doesn't mean "no campaign"; it means the structural
  evidence isn't enough to attribute.
- **The score is a behavioural signal, not a verdict:** a HIGH band means anomalous
  coordinated behaviour, not proof of orchestration.
- **Coverage *about* disinformation and single-domain echoes no longer reach the high band (4/Oct/2026).** `meta_coverage_cap` caps a cluster whose dominant narrative role is `meta_analysis` (it analyses or explains disinformation rather than producing it) to ANOMALOUS; `single_domain_cap` caps a cluster where **≥90 % of links point to a single domain** (a feed/aggregator echo) to ANOMALOUS, **mass included**. Both are configurable and reversible in `config.yaml`. Real effect: HIGH **93 → 76** (18 capped). The dashboard also adds a **dead zone** in the trend (<10 % = "Stable"), stars the **dominant hypothesis** (not always H3) and surfaces the **blind-validation precision (8.3 %)** next to the high band.
- **Honest, experimental validation.** Group separation is measured with **synthetic** data
  (ARI) and curated/external layers; **none proves real FIMI detection**. Human **blind**
  validation —with separate labels for *observable coordination*, *inauthentic/manipulative
  behaviour* and *FIMI with independent external evidence*— **has already run**
  (`auditoria_high --formato blind`): 40 HIGH clusters hand-labelled on 29/Sep/2026 →
  **8.3 % coordination** (3 yes / 33 no / 4 doubtful), **0 of 40 FIMI**. Limitations:
  **a single reviewer** (no κ; a 2nd reviewer pending), a stricter definition of
  *coordination* than the earlier sampling (so September's 94.7 % is not comparable),
  and precision sampling with no recall. See `docs/README-detallado.md`.
- **Limited coverage:** X/TikTok/Instagram/Facebook/YouTube/WhatsApp are not observed
  (API cost or not public); multimodal analysis (image/video) is missing. The corpus
  depends ~95 % on Bluesky + Google News. **60-day observation window**: older signals
  expire and stop scoring (see Method).

Full detail in [`docs/ATRIBUCION-LIMITACIONES.md`](docs/ATRIBUCION-LIMITACIONES.md). The
project **documents and fixes its own biases**: for instance, commit `aa5280f` split
"domestic coordinated campaign" (now requiring real structure) from "synchronisation
without operator" and renamed a hypothesis whose name didn't match what it measured.

## 6. Architecture and how to run it

Pipeline: `COLLECTORS → RAW → NORMALIZER → FEATURES → DETECTION → CLUSTERING → SCORING
→ ATTRIBUTION → SQLITE → REPORT → DASHBOARD`. In production, a cron runs it every 6 h over
all active topics in `config.yaml`; the dashboard is published as static HTML.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python tests/generate_synthetic.py                 # synthetic validation data
python detection/run_fimi.py --input data/radar.db --tema frontera_sur   # pipeline for one topic
python detection/gen_fimi_html.py                  # static dashboard
```

Layout: `collectors/` (capture), `normalizer/`, `features/`, `detection/` (pipeline,
scoring, attribution, dashboard, health), `tests/`, `docs/`. Data model in SQLite
(`data/radar.db`); configuration in `config.yaml` (topics, keywords, weights, bands,
sources).

Docs in [`docs/`](docs/): `TAXONOMIA.md`, `SCORING.md`, `ATRIBUCION-LIMITACIONES.md`,
`TRAZABILIDAD.md`, `GOBERNANZA.md`, `RUNBOOK.md`, `FUENTES.md`, `EIPD-DPIA.md`. Detailed
(historical) version of this README: [`docs/README-detallado.md`](docs/README-detallado.md).

## 7. License and contact

**AGPL-3.0** (network copyleft): anyone who modifies it and offers it as a service must
publish their source. See [`LICENSE`](LICENSE).

- Questions, corrections or **right of reply**: **info-fimi@viajeinteligencia.com**
- Issues and code: [GitHub Issues](https://github.com/mcasrom/hybrid-fimi-radar/issues)
- Alert bot (Telegram): `@Sieg_politica_bot` (display name: RadarFIMI_bot)
