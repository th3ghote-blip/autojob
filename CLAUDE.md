# CLAUDE.md — autojob project context

Any Claude Code session in this repo reads this file automatically. It exists so
the next session doesn't waste prompts re-discovering project shape, credentials,
or the operator's preferences.

---

## What this project is

**autojob** is Andrew's (operator) job-search + AI-consulting-outreach system.

- It scrapes 11 job sources daily into Supabase
- Claude (Haiku) qualifies each job against `profile.yaml`, scoring fit and
  tagging tier_1_apply / tier_2_consulting / retainer / reject
- A Next.js dashboard (Vercel) shows the ranked leads as a Kanban + filterable
  jobs table
- The operator clicks **Draft** → GitHub Actions runs research + letter
- The operator either **Sends via Gmail** (auto, with tracking + share page)
  or **Marks as Sent** after pasting the letter into an ATS apply form
- Every recipient sees a public share page (`/share/<token>`) demonstrating
  the AI process — this is the meta-demo of AiAppGenius's capability

---

## Stack

| Layer | Tech | Why |
|---|---|---|
| DB | Supabase Postgres | RLS, free tier sufficient |
| Workers | Python (in `workers/`) | scrapers + LLM agents + Gmail SMTP |
| Cron | GitHub Actions (`.github/workflows/`) | free unlimited on public repos |
| Web | Next.js 14 App Router | dashboard + share page |
| Hosting | Vercel | free tier, auto-deploys from master |
| LLM | Anthropic Claude Haiku (qualifier) + Opus (letter writer) | |
| Email | Gmail SMTP via App Password | reuses Outreach project's setup |

---

## Live URLs / IDs

- **Web app:** https://autojob-sigma.vercel.app
- **GitHub repo:** https://github.com/th3ghote-blip/autojob (public)
- **Supabase project:** https://bgxkqlavqnzaxpinlefg.supabase.co
- **Supabase REST base:** `https://bgxkqlavqnzaxpinlefg.supabase.co/rest/v1/`
- **Vercel project:** `prj_pLccKAo47MK05Q5rFiPTv9OJPpbJ` (team `team_rB34f0WltLpVRZuKwtg5rchB`)
- **From-email:** `info@getaiappgenius.com` (Gmail App Password auth)

---

## Where the secrets live

| Secret | Where set |
|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | local `.env.local`, GitHub Actions secret, Vercel env |
| `NEXT_PUBLIC_SUPABASE_URL` + `_ANON_KEY` | same |
| `ANTHROPIC_API_KEY` | GitHub Actions secret (workers use it), Vercel env |
| `GMAIL_USER` + `GMAIL_APP_PASSWORD` | GitHub Actions secret |
| `GITHUB_TOKEN` (PAT) | Vercel env (so /api routes can dispatch workflows) |
| `APP_PASSWORD` | Vercel env (single-user dashboard auth) |

**Local `.env.local`** has the publishable + service-role keys. Don't commit it.

---

## Workflows (cron schedule)

| File | When | What |
|---|---|---|
| `discover.yml` | daily 07:00 UTC | ingest all enabled sources |
| `pipeline.yml` | daily 09:00 UTC | Haiku-qualify newly ingested has-email + recent + unscored jobs |
| `find-emails.yml` | Tue + Fri 06:30 UTC | website scrape + GitHub commit email fallback |
| `send.yml` | manual only (workflow_dispatch) | fires letter sends, including test-sends |
| `triage.yml` | manual only | one-shot title triage: archive obvious rejects + LLM-score tier-1 titles |
| `leads.yml`  | Mon 08:00 UTC + manual | Vicidial customer-prospect lead finder (DDG + vicidial.org forum + Reddit) → Haiku classifier |

All workflows are dispatchable via `gh workflow run <file> --repo th3ghote-blip/autojob`.

---

## Sources (11 total, configured in DB `sources` table)

| slug | kind | notes |
|---|---|---|
| `hn_whoshiring` | html | Algolia `/search_by_date`, last ~95 days |
| `hn_freelancer` | html | 99% SEEKING WORK, very low yield |
| `greenhouse` | ats | 60 AI-startup companies seeded |
| `lever` | ats | 9 companies (Palantir alone gives 226) |
| `ashby` | ats | 66 companies — largest pool (OpenAI, Cohere, Mistral, etc.) |
| `ai_jobs` | html | aijobs.net, modern markup |
| `remoteok` | api | free JSON feed |
| `weworkremotely` | rss | RSS, filters to AI-flavoured |
| `remotive` | api | free JSON API |
| `jobicy` | api | returning 0 — parser bug, low priority |
| `linkedin` | html | Cloudflare gates GH Actions IPs, returned 1 |
| `reddit` | api | rate-limited from cloud IPs |
| `upwork` | html | Playwright stub, needs auth state |
| `wellfound` | html | Playwright stub, needs auth state |
| `ycombinator` | html | Playwright stub, needs auth state |

---

## Operator profile (the source of truth)

See [`profile.yaml`](profile.yaml). Owned by the operator — when he says
"forget VoiceCenter" or "English-first," update this file AND
`workers/profile.py::profile_for_prompt` if the schema changes.

Hard rules in `profile.yaml`:
- Identity: Andrew, AiAppGenius, Costa del Sol Spain
- Native: English. Bonus: PT-BR, Spanish — **only invoke when the company has
  explicit LATAM/Iberian/BR signal** (the prompt enforces this strictly,
  no "if you ever have LATAM execs" hedges)
- Comp floors: $100k FT, $1k/day consulting, $2.5k/mo retainer
- Reject: junior, MLOps infra, staff/principal, on-site outside Spain/Gibraltar
- Tier 1: FDE, applied AI, founding eng (bootstrapped only), solutions
  engineer, customer engineer, founder's associate (technical, <30p)
- Tier 2: founding eng at well-funded YC, senior FS at growth-stage, AI eng
  at mid-size co — pitch consulting not hire

---

## Letter agent (workers/agents/letter.py) hard rules

1. **Never claim a skill not in the profile.** No "Django/Flutter in scope"
   if those aren't in his edges. When stack mismatches, frame honestly.
2. **Honest bridge or bail.** If no defensible angle: return empty body_md
   + skipped_reason, mark outreach lost.
3. **English-first, no speculation.** Don't invoke trilingual edge unless
   the company has explicit LATAM/Iberia/BR signal. No "if you ever" hedges.
4. **Application gates are sacred.** Scan post for "use subject line X",
   "include word Y", "tell us about Z" — obey precisely or the email gets
   auto-archived.
5. **Two delivery modes.** If `job.contact_email` present → email format
   ("Hi name," + sig). If absent → form-paste format (no greeting, no sig,
   share link as labelled URL line).

---

## Common operations

```bash
# Trigger a single source discovery
gh workflow run discover.yml --repo th3ghote-blip/autojob -f source=ashby

# Draft a letter for one job (after user clicks Draft button, or manually)
gh workflow run pipeline.yml --repo th3ghote-blip/autojob -f job_id=<uuid>

# Re-run qualifier batch
gh workflow run pipeline.yml --repo th3ghote-blip/autojob -f max=400

# Run title triage (archive reject titles + LLM-score tier-1 titles)
gh workflow run triage.yml --repo th3ghote-blip/autojob -f max_llm=600

# Send a single outreach (real recruiter)
gh workflow run send.yml --repo th3ghote-blip/autojob -f outreach_id=<uuid>

# Test send to operator's own inbox
gh workflow run send.yml --repo th3ghote-blip/autojob \
  -f outreach_id=<uuid> -f test_to=th3ghote@gmail.com

# Vicidial lead finder
gh workflow run leads.yml --repo th3ghote-blip/autojob                          # full run
gh workflow run leads.yml --repo th3ghote-blip/autojob -f mode=scrape-only      # discover only
gh workflow run leads.yml --repo th3ghote-blip/autojob -f mode=classify-only    # score backlog
gh workflow run leads.yml --repo th3ghote-blip/autojob -f dry_run=true          # smoke test

# Quick Supabase queries (operator runs these often)
SUPA=https://bgxkqlavqnzaxpinlefg.supabase.co
SUPA_KEY=sb_secret_<...>  # find in .env.local
curl -s "$SUPA/rest/v1/jobs?select=id&realism_tier=eq.tier_1_apply" \
  -H "apikey: $SUPA_KEY" -H "Authorization: Bearer $SUPA_KEY" \
  -H "Prefer: count=exact" -I | grep -i content-range
```

---

## Pre-flight checklist for Claude when changing code in this repo

Things to do **before saying "pushed, will surface results":**

- [ ] If you renamed/restructured a field in `profile.yaml` or a Python module,
      `grep -r "<old_name>"` the codebase. Every callsite must be updated.
- [ ] If you changed a workflow YAML, run a one-shot dispatch immediately
      after pushing to verify the action even starts (catches syntax errors
      that fail silently).
- [ ] If you changed a Next.js page or API route, run `npm run build` locally
      before pushing. TypeScript errors block the Vercel build.
- [ ] If you wrote a SQL filter that uses an embedded relation
      (e.g. `companies.name=eq.X`), remember PostgREST embed filters
      DON'T restrict parent rows. Either use `source_id=eq.<id>` after a
      lookup, or `!inner` modifier.
- [ ] If you wrote an INSERT to Supabase REST, include `"Prefer":
      "return=representation"` if you need the inserted row back. Without it
      you get an empty body and your `data[0]` access crashes.
- [ ] If you changed the qualifier prompt, manually score one job (any tier)
      and check the output JSON before declaring done. The prompt drifts.
- [ ] If you changed the letter prompt, redraft an existing letter and read
      the body for hallucinations (especially: invented skills, geographies,
      speculative trilingual hedges).
- [ ] If you wrote a `for x in y` loop that may execute zero times despite a
      non-empty list, log inside the loop to verify it ran. Buffered stdout
      hides this.

---

## Operator preferences (sticky)

- Push every code change to master immediately. Operator deploys via Vercel
  on master push.
- Operator wants honest assessments, not flattery. If a feature is unlikely
  to pay off, say so.
- Operator pivots spec mid-build — that's fine, just track the cost of rework
  honestly.
- All links to files/dirs/lines/commits must be clickable markdown.
- VoiceCenter is NOT his project. Don't reference it. Single brand: AiAppGenius.
