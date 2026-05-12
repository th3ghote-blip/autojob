import { redirect } from 'next/navigation'
import Link from 'next/link'
import Shell from '@/components/Shell'
import DeleteOutreachButton from '@/components/DeleteOutreachButton'
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
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Pipeline</h1>
        <p className="text-sm text-slate-400">{cards.length} active</p>
      </div>
      <div className="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-9 gap-3">
        {STAGES.map((stage) => (
          <Column key={stage} stage={stage} cards={grouped[stage]} />
        ))}
      </div>
    </Shell>
  )
}

const STAGE_GRADIENTS: Record<string, string> = {
  new:           'from-amber-500/30 to-orange-500/30',
  researching:   'from-sky-500/30 to-blue-500/30',
  drafting:      'from-rose-500/30 to-pink-500/30',
  ready_to_send: 'from-violet-500/40 to-purple-500/40',
  sent:          'from-emerald-500/30 to-teal-500/30',
  opened:        'from-emerald-500/40 to-green-500/40',
  replied:       'from-cyan-500/40 to-emerald-500/40',
  demo_booked:   'from-fuchsia-500/40 to-pink-500/40',
  won:           'from-yellow-400/40 to-amber-500/40',
}

function Column({ stage, cards }: { stage: string; cards: Card[] }) {
  const grad = STAGE_GRADIENTS[stage] || 'from-slate-500/20 to-slate-700/20'
  return (
    <div className="bg-white/[0.025] border border-white/5 rounded-xl p-2 min-h-[60vh]">
      <div className="flex items-center justify-between text-[10px] uppercase font-semibold tracking-[0.12em] px-1.5 mb-2.5">
        <span className={`bg-gradient-to-r ${grad} bg-clip-text text-transparent`}>{stage.replace(/_/g, ' ')}</span>
        <span className="text-slate-500">{cards.length}</span>
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
    <div className="relative group">
      <DeleteOutreachButton outreachId={card.outreach_id} variant="icon" />
      <Link
        href={`/jobs/${card.job_id}`}
        className="block bg-white/[0.04] border border-white/10 rounded-lg p-2 hover:bg-white/[0.07] hover:border-violet-500/40 transition-colors"
      >
        <div className="text-sm font-medium leading-tight line-clamp-2 text-slate-100 pr-5">{card.job_title}</div>
      <div className="text-xs text-slate-400 mt-1">{card.company_name}</div>
      <div className="flex items-center justify-between mt-2 text-[10px] text-slate-500">
        <span className="px-1.5 py-0.5 bg-white/[0.06] rounded font-mono text-slate-400">{card.source_slug}</span>
        {card.fit_score != null && (
          <span className={card.fit_score >= 60 ? 'text-emerald-400' : 'text-slate-500'}>
            fit {card.fit_score}
          </span>
        )}
      </div>
      {card.last_share_click_at && (
        <div className="mt-1 text-[10px] text-emerald-400 font-medium">📨 demo opened</div>
      )}
      </Link>
    </div>
  )
}
