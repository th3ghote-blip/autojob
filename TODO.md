# autojob — TODO

## Active

- [ ] Pivot smoke test: `gh workflow run leads.yml --repo th3ghote-blip/autojob` with the new software-review source + consulting buyer-fit classifier
- [ ] Curate 30-40 non-tech-AI ATS seed companies (Greenhouse/Lever/Ashby) for Andrew to review — recruiting agencies, retail, professional services, healthcare admin, real estate
- [ ] After SQL update of ATS seeds → re-run discover → re-run leads pipeline to bring consulting-buyer prospects into `/leads`
- [ ] Make `/leads` the home tab; disable `discover.yml` + `pipeline.yml` cron (job-application side mothballed)
- [ ] Letter writer pivot: swap prompt from "job application" → "consulting pitch + share-page demo link"
- [ ] Fix Jobicy parser (low priority, returning 0 jobs)

## Done

- [x] Foundation: 11 sources + Haiku qualifier + Opus letter writer + Gmail SMTP + share pages
- [x] Free RSS sources added (Remotive, WeWorkRemotely)
- [x] ATS seeds expanded (Greenhouse 60, Lever 9, Ashby 66) → +2,500 jobs
- [x] Email finder: website scrape + GitHub commit fallback
- [x] Triage worker: archive title-rejects + LLM-score tier-1 titles
- [x] Form-paste letter mode for ATS-only roles + Mark-as-sent
- [x] Vicidial lead finder Phase 1: confirmed 0 hits in existing 7k jobs (wrong dataset)
- [x] Vicidial lead finder Phase 2: `leads` table + DDG/forum/Reddit scrapers + Haiku classifier + `/leads` UI + weekly cron
- [x] First Vicidial leads run: 82 leads, 5 prospects (Dial Fusion + GOSAT identifiable)
- [x] Strategic pivot: target = consulting buyers ($1-2.5k/mo retainers) + AI-advisory clients, NOT FT job applications
- [x] Drop forum + reddit sources (no anonymous-poster outreach)
- [x] Add `workers/leads/software_review.py` (Capterra / SoftwareAdvice profile scraper, 17 tools seeded)
- [x] Rewrite `workers/leads/classifier.py` for generic consulting buyer-fit (replaces Vicidial-specific prompt)
