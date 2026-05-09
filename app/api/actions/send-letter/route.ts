import { NextRequest, NextResponse } from 'next/server'
import { isOwner } from '@/lib/auth'

const REPO = 'th3ghote-blip/autojob'

export async function POST(req: NextRequest) {
  if (!isOwner()) return NextResponse.json({ error: 'unauthorized' }, { status: 401 })

  const body = await req.json().catch(() => ({}))
  const outreachId: string | undefined = body.outreach_id
  if (!outreachId) return NextResponse.json({ error: 'outreach_id required' }, { status: 400 })

  const token = process.env.GITHUB_TOKEN
  if (!token) {
    return NextResponse.json({ error: 'GITHUB_TOKEN missing' }, { status: 500 })
  }

  const res = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/send.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'X-GitHub-Api-Version': '2022-11-28',
      },
      body: JSON.stringify({
        ref: 'master',
        inputs: { outreach_id: outreachId, max: '0' },
      }),
    },
  )

  if (!res.ok) {
    const text = await res.text()
    return NextResponse.json({ error: `dispatch failed: ${res.status} ${text}` }, { status: 502 })
  }

  return NextResponse.json({ ok: true, message: 'Send queued — check /pipeline in ~60s' })
}
