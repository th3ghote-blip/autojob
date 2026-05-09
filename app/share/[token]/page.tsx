import { notFound } from 'next/navigation'
import { headers } from 'next/headers'
import { marked } from 'marked'
import { supabaseAdmin } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

const STEP_KIND_LABELS: Record<string, { label: string; emoji: string }> = {
  source_discovered: { label: 'Found your job posting', emoji: '🔎' },
  listing_parsed:    { label: 'Parsed the listing',    emoji: '📄' },
  company_researched:{ label: 'Researched your company', emoji: '🧠' },
  fit_scored:        { label: 'Scored fit',             emoji: '🎯' },
  letter_drafted:    { label: 'Drafted this email',     emoji: '✍️' },
  demo_generated:    { label: 'Built this demo page',   emoji: '🛠️' },
  sent:              { label: 'Sent to you',            emoji: '📨' },
}

export default async function SharePage({ params }: { params: { token: string } }) {
  const sb = supabaseAdmin()

  const { data: link } = await sb
    .from('share_links')
    .select('*')
    .eq('token', params.token)
    .maybeSingle()
  if (!link) return notFound()
  if (link.expires_at && new Date(link.expires_at) < new Date()) return notFound()

  // Record the view (fire-and-forget; ignore errors).
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

  const job = outreach.jobs
  const company = outreach.companies

  return (
    <div className="min-h-screen bg-gradient-to-b from-white to-neutral-100">
      <header className="bg-white border-b">
        <div className="max-w-3xl mx-auto px-6 py-5">
          <div className="text-xs text-neutral-500">Demo · how this email reached you</div>
          <h1 className="text-2xl font-semibold mt-1">
            Behind the email about <span className="text-brand">{job.title}</span>
          </h1>
          <p className="text-sm text-neutral-600 mt-2">
            This page was built automatically by the same AI agent that found your{' '}
            {job.sources?.name || 'posting'}, researched {company?.name}, and drafted the message in your inbox.
            Every step it took is below — nothing curated, nothing hand-tweaked.
          </p>
        </div>
      </header>

      <section className="max-w-3xl mx-auto px-6 py-8">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
          <Stat label="The role" value={job.title} />
          <Stat label="Company" value={company?.name || '—'} />
          <Stat label="Source" value={job.sources?.name || '—'} />
        </div>

        <h2 className="text-lg font-semibold mt-10 mb-4">The agent's process</h2>
        <ol className="space-y-4">
          {(steps || []).map((s: any) => {
            const meta = STEP_KIND_LABELS[s.kind] || { label: s.title, emoji: '·' }
            return (
              <li key={s.id} className="bg-white border rounded-lg p-4 shadow-sm">
                <div className="flex items-start gap-3">
                  <div className="text-xl leading-none mt-0.5" aria-hidden>{meta.emoji}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className="text-xs uppercase tracking-wide text-neutral-500">Step {s.step_order} · {meta.label}</span>
                      <span className="text-[10px] text-neutral-400 ml-auto whitespace-nowrap">
                        {new Date(s.occurred_at).toLocaleString()}
                      </span>
                    </div>
                    <div className="font-medium mt-1">{s.title}</div>
                    {s.summary && (
                      <div
                        className="prose-letter text-sm text-neutral-700 mt-2"
                        dangerouslySetInnerHTML={{ __html: marked.parse(s.summary) as string }}
                      />
                    )}
                    {(s.model || s.tokens_used) && (
                      <div className="text-[10px] text-neutral-400 mt-3 font-mono">
                        {s.model ? `model: ${s.model}` : ''}{s.tokens_used ? ` · tokens: ${s.tokens_used}` : ''}{s.duration_ms ? ` · ${s.duration_ms}ms` : ''}
                      </div>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
          {(!steps || steps.length === 0) && (
            <li className="text-sm text-neutral-500">No process steps recorded yet.</li>
          )}
        </ol>

        {letter && (
          <>
            <h2 className="text-lg font-semibold mt-10 mb-4">The email you received</h2>
            <article className="bg-white border rounded-lg p-5 shadow-sm">
              <div className="text-xs text-neutral-500">Subject</div>
              <div className="font-medium mb-3">{letter.subject}</div>
              <div
                className="prose-letter text-sm text-neutral-800"
                dangerouslySetInnerHTML={{ __html: marked.parse(letter.body_md || '') as string }}
              />
            </article>
          </>
        )}

        <footer className="mt-12 pb-12 text-xs text-neutral-500">
          <p>
            Built by <a className="underline" href="https://getaiappgenius.com">AiAppGenius</a> ·
            this is the working system — the same scraper, researcher, and writer that touched your job posting are showing it to you now.
          </p>
        </footer>
      </section>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white border rounded p-3">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="font-medium mt-1 truncate">{value}</div>
    </div>
  )
}
