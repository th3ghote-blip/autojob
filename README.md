# AutoJob

AI agent that finds AI/high-paying jobs across job boards, researches the hiring company, drafts a personalized cover letter or consulting pitch, and sends it from `info@getaiappgenius.com` with a per-recruiter share link that shows the recruiter the exact AI process used to reach them — the meta-demo.

## What this is

- **Daily cron** scrapes 8 job sources into Supabase
- **AI pipeline** (Claude) researches each company, scores fit, drafts a letter, and writes a transparent process trail
- **Gmail send** with open + click + reply tracking (mirrors `aiappgenius-outreach`)
- **Internal dashboard** at `/` shows the full pipeline as a Kanban board
- **Recruiter share page** at `/share/[token]` shows them their own job, the research the AI did on their company, the letter draft, and a step-by-step timeline of how the agent got to them

## Architecture

```
              GitHub Actions (cron)
                     │
                     ▼
       ┌─────────────────────────────┐
       │  workers/ (Python+Playwright)│
       │  - sources/<board>.py        │   plug-in contract
       │  - agents/research.py        │
       │  - agents/letter.py          │
       │  - agents/sender.py          │
       └──────────────┬──────────────┘
                      │
                      ▼
              ┌──────────────┐
              │   Supabase   │
              └──────┬───────┘
                     │
       ┌─────────────┴─────────────┐
       ▼                           ▼
 Next.js dashboard          /share/[token]
 (owner-only)               (public, recruiter demo)
```

Workers run on GitHub Actions cron (free, public-repo). Dashboard + share pages run on Vercel.

## Sources

| Slug             | Kind  | Status |
|------------------|-------|--------|
| `hn_whoshiring`  | html  | enabled |
| `ycombinator`    | html  | enabled |
| `wellfound`      | html  | enabled |
| `remoteok`       | api   | enabled |
| `ai_jobs`        | html  | enabled |
| `greenhouse`     | ats   | enabled |
| `lever`          | ats   | enabled |
| `ashby`          | ats   | enabled |

Adding a source = drop a file in `workers/sources/<slug>.py` implementing the `Source` protocol + insert a row into the `sources` table.

## Quick start (local)

```bash
# 1. Clone + install
npm install
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r workers/requirements.txt

# 2. Configure
cp .env.local.example .env.local           # fill in service-role + Anthropic + Gmail
cp .env.local workers/.env                  # workers read the same vars

# 3. Run a single worker locally
python -m workers.runner --source hn_whoshiring --once

# 4. Start the dashboard
npm run dev
```

## Schema

See [`database/schema.sql`](database/schema.sql) — paste into Supabase SQL Editor.

Key tables:
- `sources` — plug-in registry
- `companies`, `jobs`, `job_raw` — listing data
- `outreach` — Kanban pipeline state
- `letters` — versioned cover letters
- `process_steps` — AI reasoning trail (the recruiter timeline)
- `share_links` — per-recruiter unguessable URLs
- `send_logs` / `open_events` / `click_events` — Gmail telemetry
- `worker_runs` — cron observability

## License

Private / personal project.
