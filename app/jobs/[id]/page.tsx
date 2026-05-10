import { redirect, notFound } from 'next/navigation'
import { marked } from 'marked'
import Shell from '@/components/Shell'
import LetterActions from '@/components/LetterActions'
import EditableContact from '@/components/EditableContact'
import { isOwner } from '@/lib/auth'
import { supabaseAdmin } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

// Decode HTML entities so descriptions stored as `&lt;p&gt;...` render as
// real HTML, then return for dangerouslySetInnerHTML. We accept the small
// XSS surface here because /jobs/[id] is owner-only.
function cleanDescription(raw: string | null | undefined): string {
  if (!raw) return '<p class="text-neutral-500">—</p>'
  let s = raw
  // Two-pass decode in case content was double-escaped.
  for (let i = 0; i < 2; i++) {
    s = s
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#x27;/g, "'")
      .replace(/&#39;/g, "'")
      .replace(/&nbsp;/g, ' ')
      .replace(/&amp;/g, '&')
  }
  // If the result has no tags, wrap in <p> so newlines render.
  if (!/<[a-z][\s\S]*?>/i.test(s)) {
    s = s.split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('')
  }
  return s
}

export default async function JobDetailPage({ params }: { params: { id: string } }) {
  if (!isOwner()) redirect('/login')
  const sb = supabaseAdmin()

  const { data: job } = await sb.from('jobs').select('*, companies(*), sources(slug, name)').eq('id', params.id).maybeSingle()
  if (!job) return notFound()

  const { data: outreach } = await sb.from('outreach').select('*').eq('job_id', params.id).maybeSingle()
  const { data: latestLetter } = outreach
    ? await sb.from('letters').select('*').eq('outreach_id', outreach.id).order('version', { ascending: false }).limit(1).maybeSingle()
    : { data: null }

  // Resolve {{SHARE_LINK}} to the real URL for preview. The sender does the
  // same at send time (idempotent), but old drafts may still have the token in body_md.
  let previewBodyMd: string | null = latestLetter?.body_md ?? null
  if (latestLetter && outreach && previewBodyMd?.includes('{{SHARE_LINK}}')) {
    const { data: link } = await sb.from('share_links').select('token').eq('outreach_id', outreach.id).maybeSingle()
    const { data: settings } = await sb.from('settings').select('app_url').eq('id', 1).maybeSingle()
    const appUrl = settings?.app_url?.replace(/\/$/, '') || ''
    if (link?.token && appUrl) {
      previewBodyMd = previewBodyMd.replaceAll('{{SHARE_LINK}}', `${appUrl}/share/${link.token}`)
    }
  }
  const { data: steps } = outreach
    ? await sb.from('process_steps').select('*').eq('outreach_id', outreach.id).order('step_order')
    : { data: [] }

  return (
    <Shell>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 space-y-4">
          <div>
            <a href={job.url || '#'} target="_blank" className="text-xs text-slate-500 hover:text-violet-400 hover:underline font-mono">
              {job.sources?.slug} · {job.url}
            </a>
            <h1 className="text-2xl font-semibold mt-1 text-slate-100 tracking-tight">{job.title}</h1>
            <div className="text-sm text-slate-400 mt-1">
              <span className="text-slate-200">{job.companies?.name}</span> · {job.location || (job.remote ? 'Remote' : '—')}
            </div>
          </div>

          {latestLetter ? (
            <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5">
              <div className="text-[10px] uppercase tracking-[0.15em] text-violet-300 mb-1 font-semibold">Letter v{latestLetter.version}</div>
              <div className="font-medium text-slate-100 mb-3">{latestLetter.subject}</div>
              <div
                className="prose-letter text-sm"
                dangerouslySetInnerHTML={{ __html: marked.parse(previewBodyMd || '') as string }}
              />
              <LetterActions
                outreachId={outreach?.id || null}
                letter={{ subject: latestLetter.subject, body_md: latestLetter.body_md }}
                jobUrl={job.url}
                contactEmail={job.contact_email}
                alreadySent={!!outreach?.sent_at || ['sent','opened','replied','demo_booked','won'].includes(outreach?.stage || '')}
              />
            </div>
          ) : (
            <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5 text-sm text-slate-500">No letter drafted yet.</div>
          )}

          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5">
            <div className="text-[10px] uppercase tracking-[0.15em] text-violet-300 mb-3 font-semibold">Job description</div>
            <div
              className="prose-letter text-sm leading-relaxed max-w-none"
              dangerouslySetInnerHTML={{ __html: cleanDescription(job.description) }}
            />
          </div>
        </section>

        <aside className="space-y-4">
          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5">
            <div className="text-[10px] uppercase tracking-[0.15em] text-violet-300 mb-3 font-semibold">Pipeline</div>
            <div className="text-sm space-y-1.5">
              <div className="text-slate-400">Stage: <span className="text-slate-100 font-medium">{outreach?.stage || '—'}</span></div>
              <div className="text-slate-400">Pitch: <span className="text-slate-200">{outreach?.pitch_angle || '—'}</span></div>
              <div className="text-slate-400">Contact: <EditableContact
                jobId={job.id}
                initial={job.contact_email}
                companyDomain={job.companies?.domain || null}
              /></div>
              <div className="text-slate-400">Fit: <span className="text-emerald-400 font-medium">{job.fit_score ?? '—'}</span></div>
            </div>
          </div>

          <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5">
            <div className="text-[10px] uppercase tracking-[0.15em] text-violet-300 mb-3 font-semibold">AI process trail</div>
            <ol className="space-y-3 text-sm">
              {(steps || []).map((s: any) => (
                <li key={s.id} className="border-l-2 border-violet-500/40 pl-3">
                  <div className="font-medium text-slate-100">{s.title}</div>
                  <div className="text-xs text-slate-500">{new Date(s.occurred_at).toLocaleString()} · {s.kind}</div>
                </li>
              ))}
              {(!steps || steps.length === 0) && <li className="text-slate-500">No steps yet.</li>}
            </ol>
          </div>
        </aside>
      </div>
    </Shell>
  )
}
