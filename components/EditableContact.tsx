'use client'

import { useState } from 'react'

export default function EditableContact({
  jobId,
  initial,
  companyDomain,
}: {
  jobId: string
  initial: string | null
  companyDomain?: string | null
}) {
  const [email, setEmail] = useState(initial || '')
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const suggestions: string[] = []
  if (companyDomain) {
    for (const prefix of ['careers', 'jobs', 'hiring', 'talent', 'hello', 'team']) {
      suggestions.push(`${prefix}@${companyDomain}`)
    }
  }

  async function save(value: string) {
    setBusy(true); setErr(null)
    try {
      const r = await fetch('/api/actions/update-contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, contact_email: value }),
      })
      const j = await r.json()
      if (!r.ok) throw new Error(j.error || `${r.status}`)
      setEmail(value)
      setEditing(false)
    } catch (e: any) {
      setErr(e.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!editing) {
    return (
      <span className="inline-flex items-center gap-2">
        <span className="text-slate-200">{email || <em className="text-slate-500">none</em>}</span>
        <button
          onClick={() => setEditing(true)}
          className="text-[11px] text-violet-400 hover:text-violet-300 underline underline-offset-2"
        >
          edit
        </button>
      </span>
    )
  }

  return (
    <div className="space-y-1.5">
      <div className="flex gap-1">
        <input
          autoFocus
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') save(email); if (e.key === 'Escape') setEditing(false) }}
          placeholder="recruiter@company.com"
          className="rounded-md px-2 py-1 text-sm w-full"
          disabled={busy}
        />
        <button
          onClick={() => save(email)}
          disabled={busy}
          className="text-xs bg-violet-500 hover:bg-violet-400 text-white rounded px-2 py-1 font-medium disabled:opacity-50"
        >
          {busy ? '…' : 'save'}
        </button>
        <button
          onClick={() => { setEmail(initial || ''); setEditing(false); setErr(null) }}
          className="text-xs text-slate-400 hover:text-slate-200 px-2 py-1"
        >
          cancel
        </button>
      </div>
      {suggestions.length > 0 && (
        <div className="flex flex-wrap gap-1 text-[11px]">
          <span className="text-slate-500">try:</span>
          {suggestions.map((s) => (
            <button
              key={s}
              onClick={() => setEmail(s)}
              className="text-violet-400 hover:text-violet-300 underline underline-offset-2"
            >
              {s.split('@')[0]}@…
            </button>
          ))}
        </div>
      )}
      {err && <div className="text-[11px] text-rose-400">{err}</div>}
    </div>
  )
}
