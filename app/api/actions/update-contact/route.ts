import { NextRequest, NextResponse } from 'next/server'
import { isOwner } from '@/lib/auth'
import { supabaseAdmin } from '@/lib/supabase'

export async function POST(req: NextRequest) {
  if (!isOwner()) return NextResponse.json({ error: 'unauthorized' }, { status: 401 })

  const body = await req.json().catch(() => ({}))
  const jobId: string | undefined = body.job_id
  const email: string = (body.contact_email || '').trim()
  if (!jobId) return NextResponse.json({ error: 'job_id required' }, { status: 400 })

  // Allow empty string to clear, otherwise validate.
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return NextResponse.json({ error: 'invalid email' }, { status: 400 })
  }

  const sb = supabaseAdmin()
  const { error } = await sb
    .from('jobs')
    .update({ contact_email: email || null })
    .eq('id', jobId)

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ ok: true, contact_email: email || null })
}
