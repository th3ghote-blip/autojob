import { redirect } from 'next/navigation'
import Link from 'next/link'
import Shell from '@/components/Shell'
import { isOwner } from '@/lib/auth'
import { supabaseAdmin } from '@/lib/supabase'

const STAGES = [
  'new', 'researching', 'drafting', 'ready_to_send',
  'sent', 'opened', 'replied', 'demo_booked', 'won',
] as const

type Card = {
  outreach_id: string
  stage: string
  pitch_angle: string | null
  job_id: string
  job_title: string
  job_url: string | null
  comp_min: number | null
  comp_max: number | null
  contact_email: string | null
  contact_name: string | null
  posted_at: string | null
  company_id: string
  company_name: string
  company_domain: string | null
  fit_score: number | null
  source_slug: string
  source_name: string
  sent_at: string | null
  last_opened_at: string | null
  last_share_click_at: string | null
}

export const dynamic = 'force-dynamic'

export default async function PipelinePage() {
  if (!isOwner()) redirect('/login')
  const sb = supabaseAdmin()
  const { data, error } = await sb
    .from('v_pipeline')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(500)

  if (error) {
    return <Shell active="pipeline"><pre className="text-red-600">{error.message}</pre></Shell>
  }
  const cards = (data || []) as Card[]
  const grouped: Record<string, Card[]> = Object.fromEntries(STAGES.map((s) => [s, []]))
  for (const c of cards) {
    if (grouped[c.stage]) grouped[c.stage].push(c)
  }

  return (
    <Shell active="pipeline">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">Pipeline</h1>
        <p className="text-sm text-neutral-500">{cards.length} active</p>
      </div>
      <div className="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-9 gap-3">
        {STAGES.map((stage) => (
          <Column key={stage} stage={stage} cards={grouped[stage]} />
        ))}
      </div>
    </Shell>
  )
}

function Column({ stage, cards }: { stage: string; cards: Card[] }) {
  return (
    <div className="bg-neutral-100 rounded p-2 min-h-[60vh]">
      <div className="flex items-center justify-between text-xs uppercase font-semibold tracking-wide text-neutral-500 px-1 mb-2">
        <span>{stage.replace(/_/g, ' ')}</span>
        <span>{cards.length}</span>
      </div>
      <div className="space-y-2">
        {cards.map((c) => (
          <Card key={c.outreach_id} card={c} />
        ))}
      </div>
    </div>
  )
}

function Card({ card }: { card: Card }) {
  return (
    <Link
      href={`/jobs/${card.job_id}`}
      className="block bg-white border rounded p-2 hover:shadow-sm transition"
    >
      <div className="text-sm font-medium leading-tight line-clamp-2">{card.job_title}</div>
      <div className="text-xs text-neutral-600 mt-1">{card.company_name}</div>
      <div className="flex items-center justify-between mt-2 text-[10px] text-neutral-500">
        <span className="px-1.5 py-0.5 bg-neutral-100 rounded">{card.source_slug}</span>
        {card.fit_score != null && (
          <span className={card.fit_score >= 60 ? 'text-emerald-600' : 'text-neutral-400'}>
            fit {card.fit_score}
          </span>
        )}
      </div>
      {card.last_share_click_at && (
        <div className="mt-1 text-[10px] text-emerald-700 font-medium">📨 demo opened</div>
      )}
    </Link>
  )
}
