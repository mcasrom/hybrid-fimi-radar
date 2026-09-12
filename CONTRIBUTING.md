# Contributing to FIMI Radar

Thanks for your interest in FIMI Radar — an open-source OSINT radar that detects
coordinated information manipulation (FIMI) in the Spanish- and French-speaking public
sphere. Contributions of all kinds are welcome: bug reports, documentation, new open
sources, detection improvements, translations and code.

This project is released under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.
By contributing, you agree that your contributions are licensed under the same terms.

## Guiding principles

- **Signal, not attribution.** The radar observes *behaviour* (coordination, amplification,
  anomaly); it never attributes content to an actor without evidence. `UNKNOWN` is a valid
  result. Please keep this principle in any change.
- **Transparency.** Scores must remain explainable (component breakdown) and reproducible
  (version, weights, bands, window). Document what the system cannot see.
- **Only public data.** No private accounts, no profiling of individuals, no personal data.

## Ways to contribute

- **Report a bug / request a feature:** open an issue describing what you expected and what
  happened, with steps to reproduce if possible.
- **Improve documentation:** `README.md` and `docs/` (SCORING, ATRIBUCION-LIMITACIONES,
  TRAZABILIDAD, FUENTES, GOBERNANZA).
- **Add or fix a source:** open sources (RSS, public Telegram, Bluesky, Reddit, Google News)
  must be publicly accessible and return fresh content. Note bias/reliability/language.
- **Code:** fork the repo, create a topic branch, and open a pull request.

## Development setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Run the pipeline on an existing database
.venv/bin/python detection/run_fimi.py --input data/radar.db --db data/radar.db --tema frontera_sur

# Regenerate the static dashboard
.venv/bin/python detection/gen_fimi_html.py
```

Secrets live only in `.env` (gitignored). Never commit credentials, tokens or the database.

## Pull requests

- Keep changes focused and explain the *why*, not only the *what*.
- Run `python -m compileall -q -x '(\.venv|__pycache__)' .` before opening the PR.
- Add or update documentation when you change behaviour.
- CI runs compile + lint + synthetic data generation on every push (see `.github/workflows/`).

## Governance

Topic lifecycle (pilot → production → closure) is documented in `docs/GOBERNANZA.md`. The
system only *suggests*; humans decide. Changes of state are recorded in the audit log
(bitácora).

## Contact

Questions? Write to **info-fimi@viajeinteligencia.com**.
