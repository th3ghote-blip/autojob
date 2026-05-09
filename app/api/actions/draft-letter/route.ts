import { NextRequest, NextResponse } from 'next/server'
import { isOwner } from '@/lib/auth'

const REPO = 'th3ghote-blip/autojob'

export async function POST(req: NextRequest) {
  if (!isOwner()) return NextResponse.json({ error: 'unauthorized' }, { status: 401 })

  const body = await req.json().catch(() => ({}))
  const jobId: string | undefined = body.job_id
  if (!jobId) return NextResponse.json({ error: 'job_id required' }, { status: 400 })

  const token = process.env.GITHUB_TOKEN
  if (!token) {
    return NextResponse.json({
      error: 'GITHUB_TOKEN not set in Vercel env — required to dispatch letter workflow',
    }, { status: 500 })
  }

  // Dispatch pipeline.yml in single-job mode.
  const res = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/pipeline.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'X-GitHub-Api-Version': '2022-11-28',
      },
      body: JSON.stringify({
        ref: 'master',
        inputs: { job_id: jobId, max: '0' },
      }),
    },
  )

  if (!res.ok) {
    const text = await res.text()
    return NextResponse.json({ error: `dispatch failed: ${res.status} ${text}` }, { status: 502 })
  }

  return NextResponse.json({ ok: true, message: 'Drafting started — check /pipeline in ~60s' })
}
