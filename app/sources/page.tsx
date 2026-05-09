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
      <h1 className="text-2xl font-semibold mb-4">Sources</h1>
      <table className="w-full text-sm bg-white border rounded">
        <thead className="bg-neutral-50">
          <tr className="text-left">
            <th className="p-2">Slug</th>
            <th className="p-2">Name</th>
            <th className="p-2">Status</th>
            <th className="p-2">Last run</th>
            <th className="p-2">Last 7d</th>
            <th className="p-2">Total</th>
            <th className="p-2">Errors 7d</th>
          </tr>
        </thead>
        <tbody>
          {(health || []).map((s: any) => (
            <tr key={s.id} className="border-t">
              <td className="p-2 font-mono text-xs">{s.slug}</td>
              <td className="p-2">{s.name}</td>
              <td className="p-2">
                <span className={
                  s.last_status === 'ok' ? 'text-emerald-600' :
                  s.last_status === 'error' ? 'text-red-600' :
                  s.last_status === 'partial' ? 'text-amber-600' : 'text-neutral-400'
                }>
                  {s.last_status || '—'}
                </span>
              </td>
              <td className="p-2">{s.last_run_at ? new Date(s.last_run_at).toLocaleString() : '—'}</td>
              <td className="p-2">{s.jobs_last_7d}</td>
              <td className="p-2">{s.total_jobs}</td>
              <td className="p-2">{s.errors_last_7d > 0 ? <span className="text-red-600">{s.errors_last_7d}</span> : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="text-lg font-semibold mt-8 mb-3">Recent runs</h2>
      <table className="w-full text-sm bg-white border rounded">
        <thead className="bg-neutral-50">
          <tr className="text-left">
            <th className="p-2">When</th>
            <th className="p-2">Kind</th>
            <th className="p-2">Status</th>
            <th className="p-2">Found</th>
            <th className="p-2">New</th>
            <th className="p-2">Errors</th>
            <th className="p-2">CI run</th>
          </tr>
        </thead>
        <tbody>
          {(runs || []).map((r: any) => (
            <tr key={r.id} className="border-t">
              <td className="p-2">{new Date(r.started_at).toLocaleString()}</td>
              <td className="p-2 font-mono text-xs">{r.worker_kind}</td>
              <td className="p-2">{r.status}</td>
              <td className="p-2">{r.found_count}</td>
              <td className="p-2">{r.new_count}</td>
              <td className="p-2">{r.error_count}</td>
              <td className="p-2">
                {r.github_run_url ? (
                  <a href={r.github_run_url} target="_blank" className="text-brand underline">↗</a>
                ) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Shell>
  )
}
