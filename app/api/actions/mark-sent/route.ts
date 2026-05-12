import { NextRequest, NextResponse } from 'next/server'
import { isOwner } from '@/lib/auth'
import { supabaseAdmin } from '@/lib/supabase'

/**
 * Manually mark an outreach as sent (for ATS form applications where we
 * can't auto-detect delivery). Logs a process_step and advances stage.
 */
export async function POST(req: NextRequest) {
  if (!isOwner()) return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  const body = await req.json().catch(() => ({}))
  const outreachId: string | undefined = body.outreach_id
  const note: string = (body.note || '').trim()
  if (!outreachId) return NextResponse.json({ error: 'outreach_id required' }, { status: 400 })

  const sb = supabaseAdmin()

  // Advance stage to sent.
  const { error: updErr } = await sb
    .from('outreach')
    .update({ stage: 'sent', sent_at: new Date().toISOString() })
    .eq('id', outreachId)
  if (updErr) return NextResponse.json({ error: updErr.message }, { status: 500 })

  // Mark the latest letter as sent too.
  const { data: latest } = await sb
    .from('letters')
    .select('id, version')
    .eq('outreach_id', outreachId)
    .order('version', { ascending: false })
    .limit(1)
    .maybeSingle()
  if (latest?.id) {
    await sb.from('letters').update({ sent: true }).eq('id', latest.id)
  }

  // Find next step_order for the process trail.
  const { data: steps } = await sb
    .from('process_steps')
    .select('step_order')
    .eq('outreach_id', outreachId)
    .order('step_order', { ascending: false })
    .limit(1)
  const nextOrder = (steps?.[0]?.step_order || 0) + 1

  await sb.from('process_steps').insert({
    outreach_id: outreachId,
    step_order: nextOrder,
    kind: 'sent',
    title: 'Submitted via apply form',
    summary:
      'The operator pasted this letter into the company\'s application form and submitted it manually. ' +
      (note ? `\n\nNote: ${note}` : ''),
    visible_to_recruiter: true,
  })

  return NextResponse.json({ ok: true })
}
