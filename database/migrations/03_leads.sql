-- 03_leads.sql — Vicidial customer prospects (and future lead types)
--
-- Separate from `jobs` because the data shape differs:
--   - leads are signals that a company runs Vicidial (or could buy it),
--     not roles for Andrew to apply to
--   - source URLs are forum posts / Reddit / search-result pages, not ATS listings
--   - the "company name" is often best-guess until manual triage
--
-- One row per unique (source, source_url). Re-running a scraper does NOT
-- duplicate; it can only update fields on an existing row.

create table if not exists leads (
  id uuid primary key default gen_random_uuid(),
  lead_kind text not null default 'vicidial',     -- future-proof: 'vicidial' | 'other_dialer' | ...
  source text not null,                            -- 'google' | 'vicidial_forum' | 'reddit' | 'manual'
  source_url text not null,                        -- canonical URL of the post / search hit
  title text,                                      -- post title / search snippet headline
  company_name text,                               -- best-guess company name
  company_domain text,                             -- normalized domain if extractable
  excerpt text,                                    -- ~500 char snippet of the signal
  install_size_guess text,                         -- '10-50' | '50-200' | '200+' | 'unknown'
  signal_kind text,                                -- 'hiring' | 'customer_mention' | 'forum_post' | 'support_request' | 'job_post'
  posted_at timestamptz,
  fit_score integer,                               -- 0-100, Haiku-assigned
  classification text,                             -- 'prospect' | 'consultant_seeking_work' | 'unrelated' | 'unknown'
  reasoning text,                                  -- Haiku's one-line justification
  scored_at timestamptz,
  status text not null default 'new',              -- 'new' | 'qualified' | 'contacted' | 'archived'
  notes text,
  raw_json jsonb,                                  -- original payload, verbatim
  created_at timestamptz not null default now(),
  unique (source, source_url)
);

create index if not exists leads_status_idx on leads(status);
create index if not exists leads_fit_score_idx on leads(fit_score desc);
create index if not exists leads_source_idx on leads(source);
create index if not exists leads_kind_idx on leads(lead_kind);
create index if not exists leads_created_idx on leads(created_at desc);
create index if not exists leads_classification_idx on leads(classification);
