-- 02 — Add company-level recruiter contact email so the email-finder worker
-- has somewhere to write its scraped result. Jobs without a posting-level
-- contact_email fall back to this one at display + send time.
--
-- Paste in Supabase SQL Editor (project: autojob) and click Run.

alter table companies
  add column if not exists contact_email text,
  add column if not exists contact_email_source text,
  add column if not exists contact_email_priority integer,
  add column if not exists contact_email_checked_at timestamptz;

create index if not exists companies_contact_email_idx on companies(contact_email);
