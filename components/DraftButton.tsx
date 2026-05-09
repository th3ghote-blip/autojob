'use client'

import { useState } from 'react'

export default function DraftButton({ jobId, alreadyDrafted }: { jobId: string; alreadyDrafted: boolean }) {
  const [state, setState] = useState<'idle' | 'sending' | 'queued' | 'error'>(
    alreadyDrafted ? 'queued' : 'idle',
  )
  const [error, setError] = useState<string | null>(null)

  async function onClick() {
    setState('sending')
    setError(null)
    try {
      const r = await fetch('/api/actions/draft-letter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId }),
      })
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        throw new Error(j.error || `${r.status}`)
      }
      setState('queued')
    } catch (e: any) {
      setError(e.message || String(e))
      setState('error')
    }
  }

  if (state === 'queued') {
    return <span className="text-[11px] text-emerald-700">queued · check /pipeline</span>
  }
  if (state === 'sending') {
    return <span className="text-[11px] text-neutral-500">…dispatching</span>
  }
  if (state === 'error') {
    return (
      <button onClick={onClick} className="text-[11px] text-red-600 underline" title={error || ''}>
        retry
      </button>
    )
  }
  return (
    <button
      onClick={onClick}
      className="text-[11px] bg-brand text-white rounded px-2 py-1 hover:opacity-90"
    >
      Draft
    </button>
  )
}
