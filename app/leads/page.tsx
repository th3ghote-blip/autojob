import Link from 'next/link'
import { redirect } from 'next/navigation'
import Shell from '@/components/Shell'
import { isOwner } from '@/lib/auth'
import { supabaseAdmin } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

type Search = {
  classification?: string
  source?: string
  status?: string
  min_fit?: string
  hide_low?: string
  page?: string
}

const PAGE_SIZE = 50
const CLASS_OPTIONS = ['', 'prospect', 'consultant_seeking_work', 'unrelated', 'unknown']
const SOURCE_OPTIONS = ['', 'google_vicidial', 'vicidial_forum', 'reddit_vicidial']
const STATUS_OPTIONS = ['', 'new', 'qualified', 'contacted', 'archived']

export default async function LeadsPage({ searchParams }: { searchParams: Search }) {
  if (!isOwner()) redirect('/login')
  const sb = supabaseAdmin()

  const classification = searchParams.classification || ''
  const source = searchParams.source || ''
  const status = searchParams.status || ''
  const minFit = parseInt(searchParams.min_fit || '0', 10) || 0
  const hideLow = searchParams.hide_low !== '0'  // default ON — hide unrelated + <30 fit
  const page = Math.max(1, parseInt(searchParams.page || '1', 10) || 1)
  const from = (page - 1) * PAGE_SIZE
  const to = from + PAGE_SIZE - 1

  // Stats (overall, ignores filters)
  const totalRes = await sb.from('leads').select('id', { count: 'exact', head: true })
  const prospectRes = await sb
    .from('leads').select('id', { count: 'exact', head: true })
    .eq('classification', 'prospect')
  const unscoredRes = await sb
    .from('leads').select('id', { count: 'exact', head: true })
    .is('fit_score', null)
  const stats = {
    total: totalRes.count || 0,
    prospects: prospectRes.count || 0,
    unscored: unscoredRes.count || 0,
  }

  // Filtered query
  let q = sb
    .from('leads')
    .select('id,source,source_url,title,excerpt,company_name,fit_score,classification,signal_kind,install_size_guess,reasoning,status,posted_at,created_at', { count: 'exact' })
    .order('fit_score', { ascending: false, nullsFirst: false })
    .order('created_at', { ascending: false })
    .range(from, to)

  if (classification) q = q.eq('classification', classification)
  if (source) q = q.eq('source', source)
  if (status) q = q.eq('status', status)
  if (minFit > 0) q = q.gte('fit_score', minFit)
  if (hideLow) {
    q = q.gte('fit_score', 30).neq('classification', 'unrelated')
  }

  const { data: rows, count } = await q
  const total = count || 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <Shell active="leads">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-slate-100">Vicidial leads</h1>
        <div className="text-xs text-slate-500 tracking-wider">
          {stats.prospects} prospects · {stats.unscored} unscored · {stats.total} total
        </div>
      </div>

      <form className="flex flex-wrap gap-2 mb-4 text-sm bg-slate-900/40 border border-white/5 rounded-lg p-3" method="get">
        <select name="classification" defaultValue={classification} className="bg-slate-950 border border-white/10 rounded px-2 py-1 text-slate-200">
          {CLASS_OPTIONS.map((c) => <option key={c} value={c}>{c || 'any class'}</option>)}
        </select>
        <select name="source" defaultValue={source} className="bg-slate-950 border border-white/10 rounded px-2 py-1 text-slate-200">
          {SOURCE_OPTIONS.map((s) => <option key={s} value={s}>{s || 'any source'}</option>)}
        </select>
        <select name="status" defaultValue={status} className="bg-slate-950 border border-white/10 rounded px-2 py-1 text-slate-200">
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s || 'any status'}</option>)}
        </select>
        <input name="min_fit" type="number" min="0" max="100" defaultValue={minFit || ''} placeholder="min fit" className="bg-slate-950 border border-white/10 rounded px-2 py-1 text-slate-200 w-24" />
        <label className="flex items-center gap-1.5 text-slate-300">
          <input type="checkbox" name="hide_low" value="1" defaultChecked={hideLow} className="accent-violet-500" />
          hide &lt;30 & unrelated
        </label>
        <button type="submit" className="px-3 py-1 rounded bg-violet-600 hover:bg-violet-500 text-white text-xs">Apply</button>
        <Link href="/leads" className="px-3 py-1 rounded border border-white/10 text-slate-400 hover:text-white text-xs">Reset</Link>
      </form>

      <div className="border border-white/5 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/60 text-[11px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="text-left px-3 py-2">Fit</th>
              <th className="text-left px-3 py-2">Company / Title</th>
              <th className="text-left px-3 py-2">Class</th>
              <th className="text-left px-3 py-2">Source</th>
              <th className="text-left px-3 py-2">Reasoning</th>
              <th className="text-left px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {(rows || []).map((r: any) => (
              <tr key={r.id} className="border-t border-white/5 hover:bg-white/[0.02]">
                <td className="px-3 py-2 align-top">
                  <span className={fitClass(r.fit_score)}>{r.fit_score ?? '—'}</span>
                </td>
                <td className="px-3 py-2 align-top max-w-[360px]">
                  <a href={r.source_url} target="_blank" rel="noopener" className="text-slate-100 hover:text-violet-300 underline-offset-2 hover:underline">
                    {r.company_name || r.title || r.source_url}
                  </a>
                  {r.title && r.company_name ? (
                    <div className="text-xs text-slate-500 mt-0.5 line-clamp-2">{r.title}</div>
                  ) : null}
                  {r.install_size_guess && r.install_size_guess !== 'unknown' ? (
                    <div className="text-[10px] uppercase tracking-wider text-slate-600 mt-1">{r.install_size_guess} seats</div>
                  ) : null}
                </td>
                <td className="px-3 py-2 align-top">
                  <span className={classBadge(r.classification)}>{r.classification || '—'}</span>
                </td>
                <td className="px-3 py-2 align-top text-slate-400 text-xs">{r.source}</td>
                <td className="px-3 py-2 align-top text-slate-400 text-xs max-w-[320px]">
                  <div className="line-clamp-2">{r.reasoning || '—'}</div>
                </td>
                <td className="px-3 py-2 align-top text-xs text-slate-400">{r.status}</td>
              </tr>
            ))}
            {(!rows || rows.length === 0) && (
              <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-500 text-sm">
                No leads match the current filters. <Link href="/leads" className="underline">Reset</Link>.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4 text-xs text-slate-500">
          <div>Page {page} of {totalPages} · {total} leads</div>
          <div className="flex gap-2">
            {page > 1 && <Link href={pageHref(searchParams, page - 1)} className="px-3 py-1 rounded border border-white/10 hover:text-white">Prev</Link>}
            {page < totalPages && <Link href={pageHref(searchParams, page + 1)} className="px-3 py-1 rounded border border-white/10 hover:text-white">Next</Link>}
          </div>
        </div>
      )}
    </Shell>
  )
}

function fitClass(score: number | null) {
  if (score == null) return 'text-slate-600'
  if (score >= 80) return 'text-emerald-400 font-semibold'
  if (score >= 60) return 'text-amber-300 font-medium'
  if (score >= 30) return 'text-slate-300'
  return 'text-slate-600'
}

function classBadge(c: string | null) {
  const base = 'inline-block px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider '
  switch (c) {
    case 'prospect': return base + 'bg-emerald-500/10 text-emerald-300'
    case 'consultant_seeking_work': return base + 'bg-slate-500/10 text-slate-400'
    case 'unrelated': return base + 'bg-rose-500/10 text-rose-300'
    case 'unknown': return base + 'bg-amber-500/10 text-amber-300'
    default: return base + 'bg-slate-500/10 text-slate-500'
  }
}

function pageHref(sp: Search, page: number) {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(sp)) if (v && k !== 'page') params.set(k, String(v))
  params.set('page', String(page))
  return '/leads?' + params.toString()
}
