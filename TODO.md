# autojob — TODO

## Active

- [ ] Apply `database/migrations/03_leads.sql` in Supabase SQL editor
- [ ] First dry-run of leads pipeline: `gh workflow run leads.yml --repo th3ghote-blip/autojob -f dry_run=true`
- [ ] First real run: `gh workflow run leads.yml --repo th3ghote-blip/autojob`
- [ ] Review `/leads` page after first classifier pass — tune queries / classifier prompt if signal:noise is bad
- [ ] Auto-apply for Greenhouse/Lever/Ashby forms (deferred — only worth it once a prospect actually replies asking for a demo)
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
