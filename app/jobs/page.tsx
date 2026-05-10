import { redirect } from 'next/navigation'
import Link from 'next/link'
import Shell from '@/components/Shell'
import DraftButton from '@/components/DraftButton'
import { isOwner } from '@/lib/auth'
import { supabaseAdmin } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

type Search = {
  status?: string
  source?: string
  min_fit?: string
  has_email?: string
  posted_within?: string
  remote_only?: string
  hide_rejected?: string
  q?: string
  page?: string
  sort?: string
}

const PAGE_SIZE = 50
const STATUS_OPTIONS = ['', 'new', 'qualified', 'skipped', 'archived']

export default async function JobsListPage({ searchParams }: { searchParams: Search }) {
  if (!isOwner()) redirect('/login')
  const sb = supabaseAdmin()

  // Stats counts (overall, ignores filters).
  const stats = await fetchStats(sb)

  // Build filtered query.
  const status = searchParams.status || ''
  const source = searchParams.source || ''
  const minFit = parseInt(searchParams.min_fit || '0', 10) || 0
  // Default ON — without an email there's nothing to send. Use '0' to browse no-email ATS roles.
  const hasEmail = searchParams.has_email !== '0'
  const postedWithin = searchParams.posted_within ?? '7'  // default: last 7 days
  // Default ON for remote_only and hide_rejected. Use '0' to opt out.
  const remoteOnly = searchParams.remote_only !== '0'
  const hideRejected = searchParams.hide_rejected !== '0'
  const sort = searchParams.sort || 'fit'  // default: highest qualifier score first
  const q = (searchParams.q || '').trim()
  const page = Math.max(1, parseInt(searchParams.page || '1', 10) || 1)
  const from = (page - 1) * PAGE_SIZE
  const to = from + PAGE_SIZE - 1

  let postedAfter: string | null = null
  if (postedWithin && postedWithin !== 'any') {
    const days = parseInt(postedWithin, 10)
    if (days > 0) {
      postedAfter = new Date(Date.now() - days * 86400 * 1000).toISOString()
    }
  }

  // Resolve source slug -> id BEFORE the main query so we can filter on jobs.source_id
  // (PostgREST embedded filters don't restrict the parent, only the join).
  let sourceId: string | null = null
  if (source) {
    const { data: srow } = await sb.from('sources').select('id').eq('slug', source).maybeSingle()
    sourceId = srow?.id || null
    if (!sourceId) {
      // Unknown slug — return zero rows rather than silently ignoring the filter.
      return (
        <Shell active="jobs">
          <div className="bg-white border rounded p-6 text-sm text-neutral-500">
            Unknown source: <code>{source}</code>. <Link href="/jobs" className="underline">Reset filters</Link>.
          </div>
        </Shell>
      )
    }
  }

  let query = sb
    .from('jobs')
    .select(
      'id, title, url, location, remote, comp_min, comp_max, contact_email, posted_at, status, skip_reason, ' +
        'fit_score, realism_tier, qualifier_reasoning, ' +
        'sources(slug, name, kind), companies(name), ' +
        'outreach(stage, pitch_angle, letters(id))',
      { count: 'exact' },
    )
    .order(
      sort === 'fit' ? 'fit_score' : (sort === 'posted' ? 'posted_at' : 'created_at'),
      { ascending: false, nullsFirst: false },
    )
    .range(from, to)

  if (status) query = query.eq('status', status)
  if (sourceId) query = query.eq('source_id', sourceId)
  if (hasEmail) query = query.not('contact_email', 'is', null)
  if (postedAfter) query = query.gte('posted_at', postedAfter)
  if (q) query = query.or(`title.ilike.%${q}%,description.ilike.%${q}%`)
  // min_fit applies to companies.fit_score; supabase REST doesn't support a join-filter cleanly
  // for single-row joins. We filter post-fetch below if min_fit > 0.

  const { data: rows, count } = await query

  let items = (rows || []) as any[]
  if (minFit > 0) items = items.filter((r) => (r.fit_score || 0) >= minFit)
  if (remoteOnly) items = items.filter(isRemoteFriendly)
  if (hideRejected) items = items.filter((r) => !matchesRejectPattern(r))

  // De-duplicate (company, title) — Greenhouse/Lever post the same role
  // across many cities as separate listings. Keep the most-recent variant
  // and merge the others' locations + job_ids into a "variants" field.
  items = dedupeByCompanyAndTitle(items, sort)

  // List of sources for the filter dropdown.
  const { data: sources } = await sb.from('sources').select('slug, name').order('slug')

  return (
    <Shell active="jobs">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">Jobs</h1>
        <div className="text-sm text-neutral-500 flex gap-3">
          <span>total: <b>{stats.total}</b></span>
          <span>new: <b>{stats.new}</b></span>
          <span className="text-emerald-600">qualified: <b>{stats.qualified}</b></span>
          <span className="text-neutral-400">skipped: <b>{stats.skipped}</b></span>
        </div>
      </div>

      <form className="bg-white border rounded p-3 mb-4 flex flex-wrap gap-3 items-end text-sm">
        <Field label="Status">
          <select name="status" defaultValue={status} className="border rounded px-2 py-1">
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{s || 'all'}</option>
            ))}
          </select>
        </Field>
        <Field label="Source">
          <select name="source" defaultValue={source} className="border rounded px-2 py-1">
            <option value="">all</option>
            {(sources || []).map((s: any) => (
              <option key={s.slug} value={s.slug}>{s.slug}</option>
            ))}
          </select>
        </Field>
        <Field label="Min fit">
          <input
            name="min_fit"
            type="number"
            min={0}
            max={100}
            defaultValue={minFit || ''}
            className="border rounded px-2 py-1 w-20"
          />
        </Field>
        <Field label="Has email">
          <select name="has_email" defaultValue={hasEmail ? '1' : '0'} className="border rounded px-2 py-1">
            <option value="1">yes (default)</option>
            <option value="0">show all</option>
          </select>
        </Field>
        <Field label="Remote OK only">
          <select name="remote_only" defaultValue={remoteOnly ? '1' : '0'} className="border rounded px-2 py-1">
            <option value="1">yes (default)</option>
            <option value="0">show all</option>
          </select>
        </Field>
        <Field label="Hide reject titles">
          <select name="hide_rejected" defaultValue={hideRejected ? '1' : '0'} className="border rounded px-2 py-1">
            <option value="1">yes (default)</option>
            <option value="0">show all</option>
          </select>
        </Field>
        <Field label="Posted within">
          <select name="posted_within" defaultValue={postedWithin} className="border rounded px-2 py-1">
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
            <option value="any">any</option>
          </select>
        </Field>
        <Field label="Sort">
          <select name="sort" defaultValue={sort} className="border rounded px-2 py-1">
            <option value="fit">fit (qualifier)</option>
            <option value="posted">posted_at</option>
            <option value="created">created_at</option>
          </select>
        </Field>
        <Field label="Search">
          <input
            name="q"
            type="search"
            defaultValue={q}
            placeholder="title or description"
            className="border rounded px-2 py-1 w-56"
          />
        </Field>
        <button className="bg-brand text-white rounded px-3 py-1 font-medium">Apply</button>
        <Link href="/jobs" className="text-neutral-500 underline px-2">reset</Link>
      </form>

      <div className="bg-white border rounded overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 sticky top-0">
            <tr className="text-left">
              <th className="p-2">Title</th>
              <th className="p-2">Company</th>
              <th className="p-2">Source</th>
              <th className="p-2">Apply</th>
              <th className="p-2">Status</th>
              <SortableTh label="Fit"     field="fit"     current={sort} search={searchParams} />
              <th className="p-2">Comp</th>
              <SortableTh label="Posted"  field="posted"  current={sort} search={searchParams} />
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((r: any) => (
              <tr key={r.id} className="border-t hover:bg-neutral-50">
                <td className="p-2 max-w-md">
                  <Link href={`/jobs/${r.id}`} className="text-brand hover:underline">
                    {r.title || '(untitled)'}
                  </Link>
                  {r._variantCount > 1 && (
                    <span
                      className="ml-2 text-[10px] bg-neutral-100 text-neutral-600 px-1.5 py-0.5 rounded"
                      title={`Same role posted in: ${r._variantLocations.join(', ')}`}
                    >
                      ×{r._variantCount} locs
                    </span>
                  )}
                  {r.skip_reason && (
                    <div className="text-[11px] text-neutral-500 mt-0.5 line-clamp-2">
                      ↳ {r.skip_reason}
                    </div>
                  )}
                </td>
                <td className="p-2">{r.companies?.name || '—'}</td>
                <td className="p-2 text-xs font-mono text-neutral-500">{r.sources?.slug}</td>
                <td className="p-2">
                  <ApplyMethodBadge job={r} />
                </td>
                <td className="p-2">
                  <StatusPill status={r.status} />
                </td>
                <td className="p-2">
                  {r.fit_score != null ? (
                    <div title={r.qualifier_reasoning || ''} className="cursor-help">
                      <span className={
                        r.fit_score >= 70 ? 'text-emerald-600 font-bold' :
                        r.fit_score >= 50 ? 'text-emerald-700' :
                        r.fit_score >= 30 ? 'text-neutral-600' :
                        'text-neutral-400'
                      }>
                        {r.fit_score}
                      </span>
                      {r.realism_tier && r.realism_tier !== 'reject' && (
                        <div className="text-[10px] text-neutral-500 leading-tight">
                          {r.realism_tier.replace('tier_1_apply','tier 1').replace('tier_2_consulting','tier 2')}
                        </div>
                      )}
                    </div>
                  ) : <span className="text-neutral-400">—</span>}
                </td>
                <td className="p-2 text-xs">
                  {fmtComp(r.comp_min, r.comp_max)}
                </td>
                <td className="p-2 text-xs text-neutral-500">
                  {r.posted_at ? new Date(r.posted_at).toLocaleDateString() : '—'}
                </td>
                <td className="p-2 text-right whitespace-nowrap">
                  <DraftButton
                    jobId={r.id}
                    alreadyDrafted={hasLetter(r)}
                  />
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={9} className="p-8 text-center text-neutral-500">No jobs match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Pager page={page} total={count || 0} search={searchParams} />
    </Shell>
  )
}

async function fetchStats(sb: ReturnType<typeof supabaseAdmin>) {
  const [total, n, q, s] = await Promise.all([
    sb.from('jobs').select('id', { count: 'exact', head: true }),
    sb.from('jobs').select('id', { count: 'exact', head: true }).eq('status', 'new'),
    sb.from('jobs').select('id', { count: 'exact', head: true }).eq('status', 'qualified'),
    sb.from('jobs').select('id', { count: 'exact', head: true }).eq('status', 'skipped'),
  ])
  return {
    total: total.count || 0,
    new: n.count || 0,
    qualified: q.count || 0,
    skipped: s.count || 0,
  }
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5 text-xs text-neutral-500">
      <span>{label}</span>
      {children}
    </label>
  )
}

// Locations we'd take + remote-friendly markers.
const REMOTE_LOCATION_RE = /\b(remote|anywhere|worldwide|distributed|spain|gibraltar|andalusia|costa del sol|europe|emea|global|wfh|work from home)\b/i
// On-site cities we will NOT take.
const ONSITE_CITY_RE = /\b(new york|nyc|san francisco|sf bay|seattle|austin|boston|chicago|los angeles|la|denver|atlanta|portland|toronto|vancouver|london|berlin|paris|amsterdam|dublin|tel aviv|bangalore|tokyo|singapore|sydney|dubai)\b/i

function isRemoteFriendly(r: any): boolean {
  if (r.remote === true) return true
  const loc = (r.location || '').toLowerCase()
  if (!loc) return true  // empty location -> assume open
  if (REMOTE_LOCATION_RE.test(loc)) return true
  if (ONSITE_CITY_RE.test(loc)) return false
  return true
}

// Title patterns that we don't want in the table — mirrors the Python hard_reject.
const REJECT_TITLE_RE = [
  /\b(jr\.?|junior|entry[- ]level|associate engineer|associate software engineer)\b/i,
  /\b(staff|principal|distinguished)\s+(software|engineer|machine learning|ml)/i,
  /\b(ml|machine learning)\s+(researcher|research scientist|research engineer)\b/i,
  /\bpretraining\b/i,
  /\bmlops\b.*\b(platform|infrastructure)\b/i,
  /\b(data\s+scientist|quantitative\s+analyst|quant)\b/i,
  /\b(office\s+manager|executive\s+assistant|receptionist|secretary|recruiter)\b/i,
  /\b(security\s+clearance|government\s+clearance|TS\/?SCI)\b/i,
  /\b(intern|internship)\b/i,
  /\b(sales|business)\s+development\s+rep/i,
  /\baccount\s+executive\b/i,
]
function matchesRejectPattern(r: any): boolean {
  const t = r.title || ''
  return REJECT_TITLE_RE.some((re) => re.test(t))
}

function dedupeByCompanyAndTitle(rows: any[], sort: string = 'fit'): any[] {
  const groups = new Map<string, any[]>()
  for (const r of rows) {
    const company = (r.companies?.name || '').trim().toLowerCase()
    const title = (r.title || '').trim().toLowerCase()
    const key = `${company}::${title}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(r)
  }
  const merged: any[] = []
  for (const variants of groups.values()) {
    if (variants.length === 1) {
      merged.push(variants[0])
      continue
    }
    // Within a duplicate group: pick the highest fit_score (or newest if tied / all null).
    variants.sort((a, b) => {
      const fa = a.fit_score ?? -1
      const fb = b.fit_score ?? -1
      if (fa !== fb) return fb - fa
      const da = a.posted_at ? new Date(a.posted_at).getTime() : 0
      const db = b.posted_at ? new Date(b.posted_at).getTime() : 0
      return db - da
    })
    const primary = variants[0]
    primary._variantCount = variants.length
    primary._variantLocations = Array.from(
      new Set(variants.map((v) => (v.location || '').trim()).filter(Boolean)),
    )
    merged.push(primary)
  }
  // Re-sort the deduped primaries by the user's chosen sort field.
  merged.sort((a, b) => {
    if (sort === 'fit') {
      const fa = a.fit_score ?? -1
      const fb = b.fit_score ?? -1
      return fb - fa
    }
    const fieldA = sort === 'created' ? 'created_at' : 'posted_at'
    const da = a[fieldA] ? new Date(a[fieldA]).getTime() : 0
    const db = b[fieldA] ? new Date(b[fieldA]).getTime() : 0
    return db - da
  })
  return merged
}

function SortableTh({ label, field, current, search }: { label: string; field: string; current: string; search: Search }) {
  const params = new URLSearchParams(search as any)
  params.set('sort', field)
  params.delete('page')  // reset to page 1 on sort change
  const isActive = current === field
  return (
    <th className="p-2">
      <a
        href={`/jobs?${params.toString()}`}
        className={
          'inline-flex items-center gap-1 hover:text-brand ' +
          (isActive ? 'text-brand font-semibold' : 'text-neutral-700')
        }
      >
        {label}{isActive && ' ↓'}
      </a>
    </th>
  )
}

function ApplyMethodBadge({ job }: { job: any }) {
  const kind = job?.sources?.kind
  if (job.contact_email) {
    return (
      <span title={`email: ${job.contact_email}`} className="text-[11px] bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded">
        📧 email
      </span>
    )
  }
  if (kind === 'ats') {
    return (
      <span title="ATS apply form (no email)" className="text-[11px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
        🔗 form
      </span>
    )
  }
  if (job.url) {
    return (
      <span title="Apply URL" className="text-[11px] bg-neutral-100 text-neutral-700 px-2 py-0.5 rounded">
        🌐 url
      </span>
    )
  }
  return <span className="text-[11px] text-neutral-400">—</span>
}

function StatusPill({ status }: { status: string }) {
  const cls =
    status === 'qualified' ? 'bg-emerald-100 text-emerald-700' :
    status === 'skipped'   ? 'bg-neutral-100 text-neutral-500' :
    status === 'archived'  ? 'bg-neutral-100 text-neutral-400' :
                              'bg-amber-100 text-amber-700'  // new
  return <span className={`text-[11px] px-2 py-0.5 rounded ${cls}`}>{status}</span>
}

function hasLetter(row: any): boolean {
  if (!row?.outreach || row.outreach.length === 0) return false
  return row.outreach.some(
    (o: any) =>
      (o.letters && o.letters.length > 0) ||
      ['ready_to_send', 'sent', 'opened', 'replied', 'demo_booked', 'won'].includes(o.stage),
  )
}

function fmtComp(lo: number | null, hi: number | null) {
  if (!lo && !hi) return '—'
  if (lo && hi) return `$${(lo / 1000).toFixed(0)}k–${(hi / 1000).toFixed(0)}k`
  return `$${((lo || hi)! / 1000).toFixed(0)}k+`
}

function Pager({ page, total, search }: { page: number; total: number; search: Search }) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  if (pages <= 1) return null
  const url = (p: number) => {
    const s = new URLSearchParams(search as any)
    s.set('page', String(p))
    return `/jobs?${s.toString()}`
  }
  return (
    <div className="flex items-center justify-between mt-3 text-sm">
      <div className="text-neutral-500">Page {page} of {pages} · {total} total</div>
      <div className="flex gap-2">
        {page > 1 && <Link href={url(page - 1)} className="px-3 py-1 border rounded">← prev</Link>}
        {page < pages && <Link href={url(page + 1)} className="px-3 py-1 border rounded">next →</Link>}
      </div>
    </div>
  )
}
