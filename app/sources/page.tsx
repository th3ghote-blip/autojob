import { redirect } from 'next/navigation'
import Shell from '@/components/Shell'
import { isOwner } from '@/lib/auth'
import { supabaseAdmin } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

export default async function SourcesPage() {
  if (!isOwner()) redirect('/login')
  const sb = supabaseAdmin()
  const { data: health } = await sb.from('v_source_health').select('*').order('slug')
  const { data: runs } = await sb
    .from('worker_runs')
    .select('id, source_id, worker_kind, status, started_at, finished_at, found_count, new_count, error_count, github_run_url')
    .order('started_at', { ascending: false })
    .limit(20)

  return (
    <Shell active="sources">
      <h1 className="text-2xl font-semibold mb-5 tracking-tight text-slate-100">Sources</h1>
      <div className="bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-white/[0.04] border-b border-white/10 text-slate-300">
            <tr className="text-left">
              <th className="p-2.5">Slug</th>
              <th className="p-2.5">Name</th>
              <th className="p-2.5">Status</th>
              <th className="p-2.5">Last run</th>
              <th className="p-2.5">Last 7d</th>
              <th className="p-2.5">Total</th>
              <th className="p-2.5">Errors 7d</th>
            </tr>
          </thead>
          <tbody>
            {(health || []).map((s: any) => (
              <tr key={s.id} className="border-t border-white/5">
                <td className="p-2.5 font-mono text-xs text-slate-300">{s.slug}</td>
                <td className="p-2.5 text-slate-300">{s.name}</td>
                <td className="p-2.5">
                  <span className={
                    s.last_status === 'ok' ? 'text-emerald-400' :
                    s.last_status === 'error' ? 'text-rose-400' :
                    s.last_status === 'partial' ? 'text-amber-400' : 'text-slate-500'
                  }>
                    {s.last_status || '—'}
                  </span>
                </td>
                <td className="p-2.5 text-slate-400 text-xs">{s.last_run_at ? new Date(s.last_run_at).toLocaleString() : '—'}</td>
                <td className="p-2.5 text-slate-300">{s.jobs_last_7d}</td>
                <td className="p-2.5 text-slate-300">{s.total_jobs}</td>
                <td className="p-2.5">{s.errors_last_7d > 0 ? <span className="text-rose-400">{s.errors_last_7d}</span> : <span className="text-slate-600">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-lg font-semibold mt-8 mb-3 text-slate-100">Recent runs</h2>
      <div className="bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-white/[0.04] border-b border-white/10 text-slate-300">
            <tr className="text-left">
              <th className="p-2.5">When</th>
              <th className="p-2.5">Kind</th>
              <th className="p-2.5">Status</th>
              <th className="p-2.5">Found</th>
              <th className="p-2.5">New</th>
              <th className="p-2.5">Errors</th>
              <th className="p-2.5">CI run</th>
            </tr>
          </thead>
          <tbody>
            {(runs || []).map((r: any) => (
              <tr key={r.id} className="border-t border-white/5">
                <td className="p-2.5 text-slate-400 text-xs">{new Date(r.started_at).toLocaleString()}</td>
                <td className="p-2.5 font-mono text-xs text-slate-300">{r.worker_kind}</td>
                <td className="p-2.5 text-slate-300">{r.status}</td>
                <td className="p-2.5 text-slate-300">{r.found_count}</td>
                <td className="p-2.5 text-slate-300">{r.new_count}</td>
                <td className="p-2.5">{r.error_count > 0 ? <span className="text-rose-400">{r.error_count}</span> : <span className="text-slate-600">—</span>}</td>
                <td className="p-2.5">
                  {r.github_run_url ? (
                    <a href={r.github_run_url} target="_blank" className="text-violet-400 hover:text-violet-300 underline">↗</a>
                  ) : <span className="text-slate-600">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Shell>
  )
}
