import { NextRequest, NextResponse } from 'next/server'
import { isOwner } from '@/lib/auth'
import { supabaseAdmin } from '@/lib/supabase'

/**
 * Delete an outreach (and everything dangling off it) + archive the job
 * so it doesn't reappear in /jobs ranked-by-fit. The job row stays for
 * dedup integrity; only the outreach side is wiped.
 */
export async function POST(req: NextRequest) {
  if (!isOwner()) return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  const body = await req.json().catch(() => ({}))
  const outreachId: string | undefined = body.outreach_id
  if (!outreachId) return NextResponse.json({ error: 'outreach_id required' }, { status: 400 })

  const sb = supabaseAdmin()

  // Get the job_id before we delete the outreach row.
  const { data: o } = await sb.from('outreach').select('job_id').eq('id', outreachId).maybeSingle()
  const jobId = o?.job_id

  // Cascade-delete children first (defensive — depending on FK config they may
  // already cascade, but explicit is safer).
  for (const table of ['process_steps', 'share_links', 'letters', 'click_events', 'open_events']) {
    if (table === 'click_events' || table === 'open_events') {
      // These hang off send_logs, not outreach directly; collect and wipe.
      const { data: logs } = await sb.from('send_logs').select('id').eq('outreach_id', outreachId)
      const ids = (logs || []).map((l: any) => l.id)
      if (ids.length) {
        await sb.from(table).delete().in('send_log_id', ids)
      }
      continue
    }
    await sb.from(table).delete().eq('outreach_id', outreachId)
  }
  await sb.from('send_logs').delete().eq('outreach_id', outreachId)
  await sb.from('outreach').delete().eq('id', outreachId)

  // Archive the job so it stops showing in the ranked /jobs list.
  if (jobId) {
    await sb
      .from('jobs')
      .update({ status: 'archived', skip_reason: 'user archived' })
      .eq('id', jobId)
  }

  return NextResponse.json({ ok: true })
}
