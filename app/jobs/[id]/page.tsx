import { redirect, notFound } from 'next/navigation'
import { marked } from 'marked'
import Shell from '@/components/Shell'
import LetterActions from '@/components/LetterActions'
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
  const { data: steps } = outreach
    ? await sb.from('process_steps').select('*').eq('outreach_id', outreach.id).order('step_order')
    : { data: [] }

  return (
    <Shell>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 space-y-4">
          <div>
            <a href={job.url || '#'} target="_blank" className="text-xs text-neutral-500 hover:underline">
              {job.sources?.slug} · {job.url}
            </a>
            <h1 className="text-2xl font-semibold mt-1">{job.title}</h1>
            <div className="text-sm text-neutral-600 mt-1">
              {job.companies?.name} · {job.location || (job.remote ? 'Remote' : '—')}
            </div>
          </div>

          {latestLetter ? (
            <div className="bg-white border rounded p-4">
              <div className="text-xs uppercase tracking-wide text-neutral-500 mb-1">Letter v{latestLetter.version}</div>
              <div className="font-medium mb-3">{latestLetter.subject}</div>
              <div
                className="prose-letter text-sm"
                dangerouslySetInnerHTML={{ __html: marked.parse(latestLetter.body_md || '') as string }}
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
            <div className="bg-white border rounded p-4 text-sm text-neutral-500">No letter drafted yet.</div>
          )}

          <div className="bg-white border rounded p-4">
            <div className="text-xs uppercase tracking-wide text-neutral-500 mb-2">Job description</div>
            <div
              className="prose-letter text-sm leading-relaxed max-w-none"
              dangerouslySetInnerHTML={{ __html: cleanDescription(job.description) }}
            />
          </div>
        </section>

        <aside className="space-y-4">
          <div className="bg-white border rounded p-4">
            <div className="text-xs uppercase tracking-wide text-neutral-500 mb-2">Pipeline</div>
            <div>Stage: <span className="font-medium">{outreach?.stage || '—'}</span></div>
            <div>Pitch: {outreach?.pitch_angle || '—'}</div>
            <div>Contact: {job.contact_email || '—'}</div>
            <div>Fit: {job.companies?.fit_score ?? '—'}</div>
          </div>

          <div className="bg-white border rounded p-4">
            <div className="text-xs uppercase tracking-wide text-neutral-500 mb-2">AI process trail</div>
            <ol className="space-y-2 text-sm">
              {(steps || []).map((s: any) => (
                <li key={s.id} className="border-l-2 border-brand/40 pl-3">
                  <div className="font-medium">{s.title}</div>
                  <div className="text-xs text-neutral-500">{new Date(s.occurred_at).toLocaleString()} · {s.kind}</div>
                </li>
              ))}
              {(!steps || steps.length === 0) && <li className="text-neutral-500">No steps yet.</li>}
            </ol>
          </div>
        </aside>
      </div>
    </Shell>
  )
}
