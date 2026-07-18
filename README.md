# hireme

One-stop personal job + competitions dashboard. Live at **https://vaibhavgit9210.github.io/hireme/**

Opens to a ranked "what should I apply to today" list: jobs scored against my profile (AI/LLM/agent engineering, FDE, evals, data engineering · Bangalore + remote), plus every open cash-prize competition in the domain.

Everything is **free and keyless** — no signups, no API keys, no paid tiers.

## How it works

- **`index.html`** — the whole dashboard, single file, no build step, no CDN.
  - Reads `data/jobs.json` + `data/competitions.json` (baked daily).
  - **Search live** button queries CORS-open free APIs straight from the browser: Remotive, Arbeitnow, Jobicy, HN "Who is Hiring" (Algolia).
  - Fit score = title/description/location keyword weights from `config.json` (same scorer as the Python side).
  - mark applied / save / hide → persisted in `localStorage` only.
  - "Search everywhere" tab: keyword deep-links into LinkedIn (24h filter), Naukri, Wellfound, Instahyre, Cutshort, YC WaaS, etc.
- **`scripts/refresh.py`** — stdlib-only fetcher run daily by GitHub Actions (`.github/workflows/refresh.yml`, 08:00 IST):
  - Aggregators: Remotive, RemoteOK, Arbeitnow, Jobicy, Himalayas (server-side only — no CORS), HN Who's Hiring.
  - **32 company ATS boards** (`companies.json`) via public Greenhouse/Lever/Ashby JSON APIs — Anthropic, OpenAI, Databricks, Sarvam, Glean, Scale, Meesho, ElevenLabs, Cursor, Sierra, Decagon…
  - Competitions: Devpost API, HackerEarth events JSON, Unstop public API (cash-prize only) + `data/competitions_seed.json` for platforms that block bots (Kaggle/ARC Prize, AIcrowd, DrivenData).
  - Scores, dedupes, keeps top 400 jobs; sorts competitions by prize value.

## Tuning

- **Add/remove target companies:** edit `companies.json` (`{name, ats: greenhouse|lever|ashby, token}`). Find a company's token by checking `boards-api.greenhouse.io/v1/boards/<token>/jobs`, `api.lever.co/v0/postings/<token>`, or `api.ashbyhq.com/posting-api/job-board/<token>`.
- **Change keywords/weights:** edit `config.json` — both the page and the fetcher read it.
- **Seed a competition manually:** append to `data/competitions_seed.json`.
- **Force refresh:** Actions tab → "Refresh jobs & competitions" → Run workflow (also pushes `gh-pages`).
