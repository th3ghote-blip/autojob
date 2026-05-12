'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

export default function DeleteOutreachButton({
  outreachId,
  redirectTo,
  variant = 'full',
}: {
  outreachId: string
  redirectTo?: string
  variant?: 'full' | 'icon'
}) {
  const router = useRouter()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function onClick(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    const ok = window.confirm(
      'Delete this outreach? The drafted letter, share link, and process trail are wiped. The job itself is archived (won\'t resurface in ranked /jobs).',
    )
    if (!ok) return
    setBusy(true)
    setErr(null)
    try {
      const r = await fetch('/api/actions/delete-outreach', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outreach_id: outreachId }),
      })
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        throw new Error(j.error || `${r.status}`)
      }
      if (redirectTo) router.push(redirectTo)
      else router.refresh()
    } catch (e: any) {
      setErr(e.message || String(e))
      setBusy(false)
    }
  }

  if (variant === 'icon') {
    return (
      <button
        onClick={onClick}
        disabled={busy}
        className="absolute top-1 right-1 size-5 grid place-items-center text-[10px] rounded-full bg-rose-500/10 text-rose-300/60 hover:bg-rose-500/30 hover:text-rose-200 transition-colors"
        title={err || 'Delete this outreach'}
      >
        {busy ? '…' : '✕'}
      </button>
    )
  }

  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="text-xs bg-rose-500/15 text-rose-300 border border-rose-500/25 rounded px-3 py-1.5 hover:bg-rose-500/25 disabled:opacity-50"
      title={err || 'Delete this outreach + archive the job'}
    >
      {busy ? 'deleting…' : '🗑 Delete'}
    </button>
  )
}
