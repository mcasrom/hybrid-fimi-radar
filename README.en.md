# FIMI Radar — A radar for foreign information manipulation and interference

## 1. What FIMI Radar is

FIMI Radar is an OSINT system that watches, using public data, **how conversation is
coordinated and amplified** across social platforms and the press around a set of topics
(southern border & Morocco, Middle East, elections, energy, AI, Sahel, hybrid threats in
Spain, defence…). It doesn't fact-check "true or false": it looks at **who pushes the same
message, at the same time and in the same way**, to surface anomalous behaviour consistent
with manipulation campaigns (FIMI). It's meant for journalists, researchers and citizens
who want to check the data themselves.

## 2. What it does NOT do

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
- **Network density:** how interconnected the group is.
  (+ content similarity and amplification)

From these it produces a **0–100 score** and a **band** (NORMAL→CRITICAL), and evaluates
**alternative hypotheses** (anti-confirmation-bias):

H1 organic viral · H2 structured domestic coordinated campaign ·
**H2b synchronised activity without operator attribution** · H3 foreign influence operation ·
H4 media amplification · H5 sustained synchronisation with diverse content (no structure) ·
H6 no conclusive evidence.

Hypotheses **do not change the score**; they are an informational reading.

## 4. Current status

Latest run snapshot (24 Sep 2026, **v0.2**):

- **9 active topics** (7 in production + 2 pilot: `elecciones`, `defensa_espana`).
- **~113,500 events** and **824 clusters** (90-day window).
- **68 RSS feeds** + 2 platform searches, 3 public Telegram channels, 2 subreddits.
- Live dashboard: https://fimi.viajeinteligencia.com · read-only API v1: `/api/v1/…`.
- Latest release: **v0.2**.

## 5. Known limitations

- **Structural attribution only:** no organisational evidence is queried (beyond a weak
  RDAP domain signal). `UNKNOWN` doesn't mean "no campaign"; it means the structural
  evidence isn't enough to attribute.
- **The score is a behavioural signal, not a verdict:** a HIGH band means anomalous
  coordinated behaviour, not proof of orchestration.
- **Limited coverage:** X/TikTok/Instagram/Facebook/YouTube/WhatsApp are not observed
  (API cost or not public); multimodal analysis (image/video) is missing.

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
python detection/run_fimi.py --tema frontera_sur   # pipeline for one topic
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
