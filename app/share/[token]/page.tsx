import { notFound } from 'next/navigation'
import { marked } from 'marked'
import { supabaseAdmin } from '@/lib/supabase'

export const dynamic = 'force-dynamic'
export const revalidate = 0
export const fetchCache = 'force-no-store'

const STEP_META: Record<string, { label: string; emoji: string; gradient: string }> = {
  source_discovered: { label: 'Found your job posting',     emoji: '🔎', gradient: 'from-violet-500 to-fuchsia-500' },
  listing_parsed:    { label: 'Parsed the listing',          emoji: '📄', gradient: 'from-sky-500 to-blue-500' },
  company_researched:{ label: 'Researched your company',     emoji: '🧠', gradient: 'from-emerald-500 to-teal-500' },
  fit_scored:        { label: 'Scored the fit',              emoji: '🎯', gradient: 'from-amber-500 to-orange-500' },
  letter_drafted:    { label: 'Drafted this email',          emoji: '✍️', gradient: 'from-rose-500 to-pink-500' },
  demo_generated:    { label: 'Built this demo page',        emoji: '🛠️', gradient: 'from-indigo-500 to-purple-500' },
  sent:              { label: 'Sent to your inbox',          emoji: '📨', gradient: 'from-emerald-500 to-green-500' },
}

export default async function SharePage({ params }: { params: { token: string } }) {
  const sb = supabaseAdmin()

  const { data: link } = await sb.from('share_links').select('*').eq('token', params.token).maybeSingle()
  if (!link) return notFound()
  if (link.expires_at && new Date(link.expires_at) < new Date()) return notFound()

  await sb.from('share_links').update({
    first_viewed_at: link.first_viewed_at || new Date().toISOString(),
    last_viewed_at: new Date().toISOString(),
    view_count: (link.view_count || 0) + 1,
  }).eq('id', link.id)

  const { data: outreach } = await sb
    .from('outreach')
    .select('*, jobs(*, sources(slug, name)), companies(*)')
    .eq('id', link.outreach_id)
    .single()
  if (!outreach) return notFound()

  const { data: steps } = await sb
    .from('process_steps')
    .select('*')
    .eq('outreach_id', link.outreach_id)
    .eq('visible_to_recruiter', true)
    .order('step_order')

  const { data: letter } = await sb
    .from('letters')
    .select('*')
    .eq('outreach_id', link.outreach_id)
    .order('version', { ascending: false })
    .limit(1)
    .maybeSingle()

  // Substitute {{SHARE_LINK}} with the actual page URL so the recruiter
  // sees the real link in the rendered letter (not the literal placeholder).
  let letterBodyMd = letter?.body_md ?? ''
  if (letterBodyMd.includes('{{SHARE_LINK}}')) {
    const { data: settings } = await sb.from('settings').select('app_url').eq('id', 1).maybeSingle()
    const appUrl = settings?.app_url?.replace(/\/$/, '') || ''
    if (appUrl) {
      letterBodyMd = letterBodyMd.replaceAll('{{SHARE_LINK}}', `${appUrl}/share/${link.token}`)
    }
  }

  const job = outreach.jobs
  const company = outreach.companies

  const totalDuration = (steps || []).reduce((acc: number, s: any) => acc + (s.duration_ms || 0), 0)
  const totalTokens = (steps || []).reduce((acc: number, s: any) => acc + (s.tokens_used || 0), 0)

  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,#1e1b4b,#0f172a_55%,#020617)] text-slate-100">
      {/* Header */}
      <header className="relative overflow-hidden border-b border-white/5">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,#6366f1_0%,transparent_45%),radial-gradient(circle_at_bottom_right,#ec4899_0%,transparent_45%)] opacity-20" />
        <div className="relative max-w-4xl mx-auto px-6 py-14">
          <div className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-violet-300 font-semibold mb-4">
            <span className="size-2 rounded-full bg-emerald-400 animate-pulse" />
            Live demo · how this email reached you
          </div>
          <h1 className="text-4xl md:text-5xl font-semibold leading-tight tracking-tight">
            Behind the email about{' '}
            <span className="bg-gradient-to-r from-violet-400 via-fuchsia-400 to-pink-400 bg-clip-text text-transparent">
              {job.title}
            </span>
          </h1>
          <p className="mt-5 text-base md:text-lg text-slate-300 max-w-2xl leading-relaxed">
            This page was built automatically by the same AI agent that found your{' '}
            <span className="text-white font-medium">{job.sources?.name || 'posting'}</span>,
            researched <span className="text-white font-medium">{company?.name}</span>,
            and drafted the message in your inbox. Every step it took is below — nothing curated, nothing hand-tweaked.
          </p>
        </div>
      </header>

      <section className="max-w-4xl mx-auto px-6 py-10">
        {/* Stat cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="The role" value={truncate(job.title, 42)} />
          <Stat label="Company" value={company?.name || '—'} />
          <Stat label="Source" value={job.sources?.name || '—'} />
          <Stat label="Steps · ms · tokens" value={`${(steps || []).length} · ${(totalDuration/1000).toFixed(1)}s · ${totalTokens.toLocaleString()}`} mono />
        </div>

        {/* Timeline */}
        <h2 className="text-2xl font-semibold mt-14 mb-6 flex items-center gap-3">
          <span className="size-1 rounded-full bg-gradient-to-r from-violet-500 to-pink-500 w-12 block" />
          The agent's process
        </h2>

        <ol className="relative ml-3">
          <div className="absolute left-[15px] top-2 bottom-2 w-px bg-gradient-to-b from-violet-500/40 via-pink-500/40 to-transparent" />
          {(steps || []).map((s: any) => {
            const meta = STEP_META[s.kind] || { label: s.title, emoji: '·', gradient: 'from-slate-500 to-slate-700' }
            return (
              <li key={s.id} className="relative pl-12 pb-6">
                <div className={`absolute left-0 top-1 size-8 rounded-full bg-gradient-to-br ${meta.gradient} flex items-center justify-center text-base shadow-lg shadow-violet-900/40`}>
                  {meta.emoji}
                </div>
                <div className="rounded-xl border border-white/10 bg-white/[0.04] backdrop-blur-sm p-5 hover:border-white/20 hover:bg-white/[0.06] transition-colors">
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <span className="text-[10px] uppercase tracking-[0.15em] text-violet-300 font-semibold">
                      Step {s.step_order} · {meta.label}
                    </span>
                    <span className="text-[10px] text-slate-500 ml-auto whitespace-nowrap font-mono">
                      {new Date(s.occurred_at).toLocaleString()}
                    </span>
                  </div>
                  <div className="font-medium mt-1 text-slate-100">{s.title}</div>
                  {s.summary && (
                    <div
                      className="prose-share text-sm text-slate-300 mt-3"
                      dangerouslySetInnerHTML={{ __html: marked.parse(s.summary) as string }}
                    />
                  )}
                  {(s.model || s.tokens_used || s.duration_ms) && (
                    <div className="text-[10px] text-slate-500 mt-4 font-mono flex flex-wrap gap-3">
                      {s.model && <span>model: <span className="text-slate-400">{s.model}</span></span>}
                      {s.tokens_used > 0 && <span>tokens: <span className="text-slate-400">{s.tokens_used.toLocaleString()}</span></span>}
                      {s.duration_ms > 0 && <span>elapsed: <span className="text-slate-400">{(s.duration_ms / 1000).toFixed(2)}s</span></span>}
                    </div>
                  )}
                </div>
              </li>
            )
          })}
          {(!steps || steps.length === 0) && (
            <li className="pl-12 text-sm text-slate-500">No process steps recorded yet.</li>
          )}
        </ol>

        {/* Letter preview */}
        {letter && (
          <>
            <h2 className="text-2xl font-semibold mt-14 mb-6 flex items-center gap-3">
              <span className="size-1 rounded-full bg-gradient-to-r from-pink-500 to-amber-500 w-12 block" />
              The email you received
            </h2>
            <article className="rounded-xl border border-white/10 bg-gradient-to-b from-white/[0.06] to-white/[0.02] p-6 shadow-2xl shadow-violet-900/20">
              <div className="text-[10px] uppercase tracking-[0.15em] text-violet-300 font-semibold">Subject</div>
              <div className="font-medium text-slate-100 mb-4">{letter.subject}</div>
              <div className="border-t border-white/10 pt-4">
                <div
                  className="prose-share text-sm text-slate-300"
                  dangerouslySetInnerHTML={{ __html: marked.parse(letterBodyMd || '') as string }}
                />
              </div>
            </article>
          </>
        )}

        <footer className="mt-16 pb-16 border-t border-white/5 pt-6">
          <p className="text-xs text-slate-500 leading-relaxed">
            Built by{' '}
            <a className="text-violet-400 hover:text-violet-300 underline underline-offset-2" href="https://getaiappgenius.com">
              AiAppGenius
            </a>{' '}
            · this is the working system — the same scraper, researcher, and writer that touched your job posting are showing it to you now. Want one of these for your team?{' '}
            <a className="text-violet-400 hover:text-violet-300 underline underline-offset-2" href="mailto:info@getaiappgenius.com">
              info@getaiappgenius.com
            </a>
          </p>
        </footer>
      </section>
    </div>
  )
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="text-[10px] uppercase tracking-[0.15em] text-slate-400 font-semibold">{label}</div>
      <div className={`font-medium mt-1.5 truncate ${mono ? 'font-mono text-xs text-violet-300' : 'text-slate-100 text-sm'}`}>{value}</div>
    </div>
  )
}

function truncate(s: string | null | undefined, n: number): string {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}
