-- AutoJob — Supabase Database Schema
-- Paste this entire file into the Supabase SQL Editor (project: autojob) and click Run.
--
-- Conventions match the aiappgenius-outreach schema:
--   - uuid primary keys (gen_random_uuid)
--   - timestamptz created_at default now()
--   - send/open/click telemetry mirrors outreach
--   - service-role key used by workers + Next.js server actions; no RLS by default
--
-- AutoJob differences vs Outreach:
--   - Plug-in job sources (sources table) so adding a new board = 1 worker file + 1 row
--   - Per-listing AI process trail (process_steps) so recruiters can see how their
--     job was found, researched, and the letter drafted (the meta-demo)
--   - Per-recruiter share links to a transparent demo page

-- ─── Sources ──────────────────────────────────────────────────────────────────
-- One row per job board. Adding a new board = drop a worker file under
-- workers/sources/<slug>.py and insert a row here.
create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,                      -- 'hn_whoshiring', 'remoteok', 'greenhouse:openai'
  name text not null,                             -- human display name
  kind text not null,                             -- 'html' | 'api' | 'ats' | 'rss'
  config_json jsonb default '{}'::jsonb,          -- per-source config (urls, company list, headers)
  enabled boolean default true,
  schedule_cron text default '0 7 * * *',         -- daily 07:00 UTC by default
  last_run_at timestamptz,
  last_status text,                               -- 'ok' | 'error' | 'partial'
  last_error text,
  created_at timestamptz default now()
);

create index if not exists sources_enabled_idx on sources(enabled);

-- ─── Companies ────────────────────────────────────────────────────────────────
create table if not exists companies (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  domain text unique,                             -- canonical key for dedupe across sources
  website text,
  hq_location text,
  size_label text,                                -- '11-50', '51-200', etc.
  funding_stage text,                             -- 'seed', 'series_a', 'public'
  funding_total_usd bigint,
  industry text,
  description text,
  research_json jsonb,                            -- Claude+web research output
  research_summary text,                          -- short human-readable digest
  last_researched_at timestamptz,
  fit_score integer default 0,                    -- 0-100, how well this fits user's offer
  notes text,
  created_at timestamptz default now()
);

create index if not exists companies_domain_idx on companies(domain);
create index if not exists companies_fit_score_idx on companies(fit_score);

-- ─── Jobs ─────────────────────────────────────────────────────────────────────
create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id),
  company_id uuid references companies(id) on delete cascade,
  external_id text,                               -- source-native id, used for dedupe per source
  title text not null,
  description text,
  comp_min integer,
  comp_max integer,
  comp_currency text default 'USD',
  location text,
  remote boolean default false,
  employment_type text,                           -- 'full_time', 'contract', 'consulting'
  contact_name text,
  contact_email text,
  contact_role text,
  url text,
  posted_at timestamptz,
  raw_id uuid,                                    -- references job_raw(id), set after insert
  status text default 'new',                      -- 'new' | 'qualified' | 'skipped' | 'archived'
  skip_reason text,
  created_at timestamptz default now(),
  unique (source_id, external_id)
);

create index if not exists jobs_company_id_idx on jobs(company_id);
create index if not exists jobs_source_id_idx on jobs(source_id);
create index if not exists jobs_status_idx on jobs(status);
create index if not exists jobs_posted_at_idx on jobs(posted_at desc);

-- ─── Job Raw ──────────────────────────────────────────────────────────────────
-- Original payload kept verbatim so we can re-parse without re-scraping.
create table if not exists job_raw (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id),
  external_id text,
  payload_json jsonb not null,
  payload_html text,
  fetched_at timestamptz default now()
);

create index if not exists job_raw_source_external_idx on job_raw(source_id, external_id);

-- ─── Outreach ─────────────────────────────────────────────────────────────────
-- One row per job we decide to pursue. This is the Kanban row.
create table if not exists outreach (
  id uuid primary key default gen_random_uuid(),
  job_id uuid references jobs(id) on delete cascade,
  company_id uuid references companies(id),
  stage text default 'new',                       -- new | researching | drafting | ready_to_send |
                                                  -- sent | opened | replied | demo_booked | won | lost
  pitch_angle text,                               -- 'job_application' | 'consulting'
  sent_at timestamptz,
  opened_at timestamptz,
  replied_at timestamptz,
  reply_classification text,
  demo_booked_at timestamptz,
  won_at timestamptz,
  lost_at timestamptz,
  lost_reason text,
  notes text,
  created_at timestamptz default now()
);

create index if not exists outreach_stage_idx on outreach(stage);
create index if not exists outreach_job_id_idx on outreach(job_id);

-- ─── Letters ──────────────────────────────────────────────────────────────────
-- Versioned cover letters / consulting pitches. Most recent = active.
create table if not exists letters (
  id uuid primary key default gen_random_uuid(),
  outreach_id uuid references outreach(id) on delete cascade,
  version integer not null default 1,
  subject text,
  body_md text,                                   -- markdown source
  body_html text,                                 -- rendered for email
  model text,                                     -- 'claude-opus-4-7' etc.
  tokens_in integer,
  tokens_out integer,
  generated_at timestamptz default now(),
  approved_at timestamptz,
  sent boolean default false
);

create index if not exists letters_outreach_id_idx on letters(outreach_id);

-- ─── Process Steps ────────────────────────────────────────────────────────────
-- The AI's reasoning trail per outreach. Renders as the timeline shown to
-- recruiters on the share page — this IS the demo of how the agent works.
create table if not exists process_steps (
  id uuid primary key default gen_random_uuid(),
  outreach_id uuid references outreach(id) on delete cascade,
  step_order integer not null,
  kind text not null,                             -- 'source_discovered' | 'listing_parsed' |
                                                  -- 'company_researched' | 'fit_scored' |
                                                  -- 'letter_drafted' | 'demo_generated' | 'sent'
  title text not null,                            -- short headline shown in timeline
  summary text,                                   -- markdown body shown when step expanded
  input_redacted_json jsonb,                      -- inputs (urls fetched, prompts, truncated)
  output_redacted_json jsonb,                     -- outputs (parsed fields, scores)
  model text,
  tokens_used integer,
  duration_ms integer,
  occurred_at timestamptz default now(),
  visible_to_recruiter boolean default true       -- false = internal-only step
);

create index if not exists process_steps_outreach_idx on process_steps(outreach_id, step_order);

-- ─── Share Links ──────────────────────────────────────────────────────────────
-- Per-recruiter unguessable token. The email links here.
-- The share page (server-rendered, no auth) shows: the job, the research,
-- the letter, and the process_steps timeline scoped to one outreach.
create table if not exists share_links (
  id uuid primary key default gen_random_uuid(),
  outreach_id uuid references outreach(id) on delete cascade,
  token text not null unique,                     -- random url-safe string, ~32 chars
  expires_at timestamptz,
  first_viewed_at timestamptz,
  last_viewed_at timestamptz,
  view_count integer default 0,
  created_at timestamptz default now()
);

create index if not exists share_links_token_idx on share_links(token);

-- ─── Send Logs ────────────────────────────────────────────────────────────────
-- Mirrors aiappgenius-outreach.send_logs so the Gmail send pipeline is reusable.
create table if not exists send_logs (
  id uuid primary key default gen_random_uuid(),
  letter_id uuid references letters(id),
  outreach_id uuid references outreach(id),
  job_id uuid references jobs(id),
  company_id uuid references companies(id),
  to_email text not null,
  to_name text,
  subject text,
  sent_at timestamptz default now(),
  status text default 'sent',                     -- 'sent' | 'bounced' | 'failed'
  opened boolean default false,
  opened_at timestamptz,
  open_count integer default 0,
  human_open_count integer default 0,
  clicked boolean default false,
  clicked_at timestamptz,
  click_count integer default 0,
  share_link_clicked boolean default false,       -- did they click the demo link specifically
  share_link_clicked_at timestamptz,
  bounced_at timestamptz,
  bounce_type text,
  bounce_reason text,
  replied_at timestamptz,
  reply_classification text,
  reply_snippet text,
  reply_raw text,
  gmail_message_id text,
  gmail_thread_id text
);

create index if not exists send_logs_outreach_id_idx on send_logs(outreach_id);
create index if not exists send_logs_status_idx on send_logs(status);
create index if not exists send_logs_thread_id_idx on send_logs(gmail_thread_id);

-- ─── Open Events ──────────────────────────────────────────────────────────────
create table if not exists open_events (
  id uuid primary key default gen_random_uuid(),
  send_log_id uuid references send_logs(id) on delete cascade,
  opened_at timestamptz default now(),
  is_bot boolean default false,
  time_since_send_ms integer,
  user_agent text
);

-- ─── Click Events ─────────────────────────────────────────────────────────────
create table if not exists click_events (
  id uuid primary key default gen_random_uuid(),
  send_log_id uuid references send_logs(id) on delete cascade,
  clicked_at timestamptz default now(),
  destination_url text,
  is_share_link boolean default false,
  user_agent text
);

-- ─── Worker Runs ──────────────────────────────────────────────────────────────
-- Observability for cron jobs. /sources page in the dashboard reads from this.
create table if not exists worker_runs (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references sources(id),
  worker_kind text,                               -- 'discover' | 'research' | 'letter' | 'send'
  started_at timestamptz default now(),
  finished_at timestamptz,
  duration_ms integer,
  found_count integer default 0,
  new_count integer default 0,
  skipped_count integer default 0,
  error_count integer default 0,
  errors_json jsonb,
  github_run_url text,
  status text default 'running'                   -- 'running' | 'ok' | 'error' | 'partial'
);

create index if not exists worker_runs_source_started_idx on worker_runs(source_id, started_at desc);
create index if not exists worker_runs_status_idx on worker_runs(status);

-- ─── Settings ─────────────────────────────────────────────────────────────────
-- Single-row config so non-secret tunables can be edited without redeploy.
create table if not exists settings (
  id integer primary key default 1,
  from_email text not null default 'info@getaiappgenius.com',
  reply_to_email text default 'info@getaiappgenius.com',
  sender_name text default 'AiAppGenius',
  sender_title text default 'Founder',
  daily_send_limit integer default 20,
  min_fit_score integer default 60,               -- below this, jobs auto-skipped
  pitch_default text default 'consulting',        -- 'job_application' | 'consulting' | 'auto'
  app_url text default 'http://localhost:3000',
  email_signature_html text default '<strong>AiAppGenius</strong><br>AI-powered software for growing businesses<br><a href="https://getaiappgenius.com">getaiappgenius.com</a>',
  updated_at timestamptz default now(),
  constraint settings_singleton check (id = 1)
);

insert into settings (id) values (1) on conflict (id) do nothing;

-- ─── Seed Sources ─────────────────────────────────────────────────────────────
-- Tier 1 + Tier 2 from the architecture plan. Add ATS targets (Greenhouse/Lever/Ashby)
-- via config_json once you have a curated AI-company list.
insert into sources (slug, name, kind, config_json, enabled) values
  ('hn_whoshiring', 'Hacker News — Who is hiring',  'html', '{"tag_filters":["ai","ml","llm","python","remote"]}'::jsonb, true),
  ('ycombinator',   'YC Work at a Startup',         'html', '{"requires_login":true,"filters":{"role_types":["eng","ml"]}}'::jsonb, true),
  ('wellfound',     'Wellfound (AngelList Talent)', 'html', '{"filters":{"role":["ai","ml","backend"],"compensation_min":100000}}'::jsonb, true),
  ('remoteok',      'RemoteOK',                     'api',  '{"feed":"https://remoteok.com/api","tags":["ai","ml","python"]}'::jsonb, true),
  ('ai_jobs',       'ai-jobs.net',                  'html', '{"base":"https://ai-jobs.net"}'::jsonb, true),
  ('greenhouse',    'Greenhouse (multi-company)',   'ats',  '{"companies":[]}'::jsonb, true),
  ('lever',         'Lever (multi-company)',        'ats',  '{"companies":[]}'::jsonb, true),
  ('ashby',         'Ashby (multi-company)',        'ats',  '{"companies":[]}'::jsonb, true)
on conflict (slug) do nothing;

-- ─── Helpful views ────────────────────────────────────────────────────────────

-- Pipeline view: one row per active outreach with everything the Kanban needs.
create or replace view v_pipeline as
select
  o.id              as outreach_id,
  o.stage,
  o.pitch_angle,
  o.sent_at,
  o.opened_at,
  o.replied_at,
  o.demo_booked_at,
  o.created_at,
  j.id              as job_id,
  j.title           as job_title,
  j.url             as job_url,
  j.comp_min,
  j.comp_max,
  j.contact_email,
  j.contact_name,
  j.posted_at,
  c.id              as company_id,
  c.name            as company_name,
  c.domain          as company_domain,
  c.fit_score,
  c.funding_stage,
  s.slug            as source_slug,
  s.name            as source_name,
  (select max(sl.opened_at) from send_logs sl where sl.outreach_id = o.id) as last_opened_at,
  (select max(sl.share_link_clicked_at) from send_logs sl where sl.outreach_id = o.id) as last_share_click_at
from outreach o
join jobs j     on j.id = o.job_id
join companies c on c.id = o.company_id
join sources s  on s.id = j.source_id;

-- Source health view: last run + health for the /sources dashboard page.
create or replace view v_source_health as
select
  s.id, s.slug, s.name, s.enabled, s.schedule_cron,
  s.last_run_at, s.last_status, s.last_error,
  (select count(*) from jobs j where j.source_id = s.id) as total_jobs,
  (select count(*) from jobs j where j.source_id = s.id and j.created_at > now() - interval '7 days') as jobs_last_7d,
  (select count(*) from worker_runs wr where wr.source_id = s.id and wr.status = 'error' and wr.started_at > now() - interval '7 days') as errors_last_7d
from sources s
order by s.enabled desc, s.slug;
