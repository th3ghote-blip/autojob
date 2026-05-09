import { NextRequest, NextResponse } from 'next/server'
import { supabaseAdmin } from '@/lib/supabase'

export async function GET(req: NextRequest, { params }: { params: { id: string } }) {
  const sendLogId = params.id
  const url = new URL(req.url)
  const dest = url.searchParams.get('u') || '/'
  const isShare = url.searchParams.get('s') === '1'
  const ua = req.headers.get('user-agent') || ''

  try {
    const sb = supabaseAdmin()
    await sb.from('click_events').insert({
      send_log_id: sendLogId,
      destination_url: dest,
      is_share_link: isShare,
      user_agent: ua.slice(0, 500),
    })
    const patch: Record<string, unknown> = {
      clicked: true,
      clicked_at: new Date().toISOString(),
    }
    if (isShare) {
      patch.share_link_clicked = true
      patch.share_link_clicked_at = new Date().toISOString()
    }
    await sb.from('send_logs').update(patch).eq('id', sendLogId)
    // Increment counters in a separate call (no atomic increment on free tier).
    const { data } = await sb.from('send_logs').select('click_count').eq('id', sendLogId).single()
    await sb.from('send_logs').update({ click_count: (data?.click_count || 0) + 1 }).eq('id', sendLogId)
  } catch {
    // never block the redirect
  }

  // basic safety: only redirect to http(s) destinations
  const safe = /^https?:\/\//i.test(dest) ? dest : '/'
  return NextResponse.redirect(safe, 302)
}
