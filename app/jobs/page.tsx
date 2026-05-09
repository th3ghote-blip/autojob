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
  q?: string
  page?: string
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
  const hasEmail = searchParams.has_email === '1'
  const q = (searchParams.q || '').trim()
  const page = Math.max(1, parseInt(searchParams.page || '1', 10) || 1)
  const from = (page - 1) * PAGE_SIZE
  const to = from + PAGE_SIZE - 1

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
      'id, title, location, remote, comp_min, comp_max, contact_email, posted_at, status, skip_reason, ' +
        'sources(slug, name), companies(name, fit_score), ' +
        'outreach(stage, pitch_angle, letters(id))',
      { count: 'exact' },
    )
    .order('created_at', { ascending: false })
    .range(from, to)

  if (status) query = query.eq('status', status)
  if (sourceId) query = query.eq('source_id', sourceId)
  if (hasEmail) query = query.not('contact_email', 'is', null)
  if (q) query = query.or(`title.ilike.%${q}%,description.ilike.%${q}%`)
  // min_fit applies to companies.fit_score; supabase REST doesn't support a join-filter cleanly
  // for single-row joins. We filter post-fetch below if min_fit > 0.

  const { data: rows, count } = await query

  let items = (rows || []) as any[]
  if (minFit > 0) items = items.filter((r) => (r.companies?.fit_score || 0) >= minFit)

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
          <input name="has_email" type="checkbox" value="1" defaultChecked={hasEmail} />
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
              <th className="p-2">Status</th>
              <th className="p-2">Fit</th>
              <th className="p-2">Tier / Pitch</th>
              <th className="p-2">Comp</th>
              <th className="p-2">Email</th>
              <th className="p-2">Posted</th>
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
                  {r.skip_reason && (
                    <div className="text-[11px] text-neutral-500 mt-0.5 line-clamp-2">
                      ↳ {r.skip_reason}
                    </div>
                  )}
                </td>
                <td className="p-2">{r.companies?.name || '—'}</td>
                <td className="p-2 text-xs font-mono text-neutral-500">{r.sources?.slug}</td>
                <td className="p-2">
                  <StatusPill status={r.status} />
                </td>
                <td className="p-2">
                  {r.companies?.fit_score != null ? (
                    <span className={r.companies.fit_score >= 60 ? 'text-emerald-600 font-medium' : 'text-neutral-500'}>
                      {r.companies.fit_score}
                    </span>
                  ) : '—'}
                </td>
                <td className="p-2 text-xs">
                  {r.outreach?.[0]?.pitch_angle || '—'}
                </td>
                <td className="p-2 text-xs">
                  {fmtComp(r.comp_min, r.comp_max)}
                </td>
                <td className="p-2 text-xs text-neutral-500 truncate max-w-[14ch]">
                  {r.contact_email || '—'}
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
              <tr><td colSpan={10} className="p-8 text-center text-neutral-500">No jobs match these filters.</td></tr>
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
