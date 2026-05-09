import { NextRequest } from 'next/server'
import { supabaseAdmin } from '@/lib/supabase'

// 1x1 transparent GIF
const GIF = Buffer.from(
  'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7',
  'base64',
)

export async function GET(req: NextRequest, { params }: { params: { id: string } }) {
  const sendLogId = params.id.replace(/\.gif$/i, '')
  const ua = req.headers.get('user-agent') || ''
  const isBot = /bot|crawl|preview|fetcher|prefetch|GoogleImageProxy|YahooMailProxy/i.test(ua)

  try {
    const sb = supabaseAdmin()
    const { data: existing } = await sb
      .from('send_logs')
      .select('id, sent_at, opened, open_count, human_open_count')
      .eq('id', sendLogId)
      .maybeSingle()
    if (existing) {
      const sentAt = existing.sent_at ? new Date(existing.sent_at).getTime() : null
      const elapsed = sentAt ? Date.now() - sentAt : null
      await sb.from('open_events').insert({
        send_log_id: sendLogId,
        is_bot: isBot,
        time_since_send_ms: elapsed,
        user_agent: ua.slice(0, 500),
      })
      await sb.from('send_logs').update({
        opened: true,
        opened_at: existing.opened ? undefined : new Date().toISOString(),
        open_count: (existing.open_count || 0) + 1,
        human_open_count: isBot ? (existing.human_open_count || 0) : (existing.human_open_count || 0) + 1,
      }).eq('id', sendLogId)
      if (!isBot) {
        await sb.from('outreach').update({ stage: 'opened', opened_at: new Date().toISOString() })
          .eq('id', (await sb.from('send_logs').select('outreach_id').eq('id', sendLogId).single()).data?.outreach_id)
          .eq('stage', 'sent')
      }
    }
  } catch {
    // pixel must always succeed
  }

  return new Response(GIF, {
    status: 200,
    headers: {
      'Content-Type': 'image/gif',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'Pragma': 'no-cache',
      'Expires': '0',
    },
  })
}
