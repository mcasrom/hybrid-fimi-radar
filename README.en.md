# FIMI Radar — Coordination and amplification signal radar

## 1. What FIMI Radar is

**Coordination and amplification signal radar:** an OSINT system that detects, from
public data, **observable patterns of synchronisation, content repetition and structural
clustering** across social platforms and the press around a set of topics (southern
border & Morocco, Middle East, elections, energy, AI, Sahel, hybrid threats in Spain,
defence…). It looks at **who pushes the same message, at the same time and in the same
way**, to surface patterns potentially consistent with coordinated influence or
manipulation activity (FIMI).

The tool **does not attribute an actor or confirm inauthenticity or a foreign campaign
by itself**: its outputs should be interpreted as **behavioural signals requiring
additional validation, contextual analysis, and organisational evidence**. It doesn't
fact-check "true or false". It's meant for journalists, researchers and citizens who
want to check the data themselves.

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
- **Content similarity** and **amplification** (a global signal of the cycle).

> **Network density** is still computed and published as a datum, but it **does not
> weight the score**: it is a transform of the same coordination axis (double counting)
> and was removed on 24-Sep-2026. It feeds the attribution module (hypothesis H3).

Each cluster also publishes **`alternative_explanations`**: alternative explanations with a
status (`supported` / `plausible` / `ruled_out`) and the **evidence** behind it — mainstream
echo, single-piece echo, organic virality, synchronisation without an operator, non-malicious
automation, legitimate mobilisation, graph artefact and *no conclusive explanation*. It is not
a "truth" classifier: it is material for human review, shown in the dashboard, the API and the
exports.

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
