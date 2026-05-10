'use client'

import { useState } from 'react'

type Props = {
  outreachId: string | null
  letter: { subject: string | null; body_md: string | null } | null
  jobUrl: string | null
  contactEmail: string | null
  alreadySent: boolean
}

export default function LetterActions({ outreachId, letter, jobUrl, contactEmail, alreadySent }: Props) {
  const [sendState, setSendState] = useState<'idle' | 'sending' | 'queued' | 'error'>(
    alreadySent ? 'queued' : 'idle',
  )
  const [testState, setTestState] = useState<'idle' | 'sending' | 'queued' | 'error'>('idle')
  const [copyState, setCopyState] = useState<'idle' | 'copied'>('idle')
  const [error, setError] = useState<string | null>(null)

  async function onCopy() {
    if (!letter) return
    const text = `Subject: ${letter.subject || ''}\n\n${letter.body_md || ''}`
    try {
      await navigator.clipboard.writeText(text)
      setCopyState('copied')
      setTimeout(() => setCopyState('idle'), 2000)
    } catch {
      // ignore
    }
  }

  async function onSend() {
    if (!outreachId) return
    setSendState('sending')
    setError(null)
    try {
      const r = await fetch('/api/actions/send-letter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outreach_id: outreachId }),
      })
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        throw new Error(j.error || `${r.status}`)
      }
      setSendState('queued')
    } catch (e: any) {
      setError(e.message || String(e))
      setSendState('error')
    }
  }

  async function onTestSend() {
    if (!outreachId) return
    const to = window.prompt('Send test to which address?', 'th3ghote@gmail.com')
    if (!to) return
    setTestState('sending')
    setError(null)
    try {
      const r = await fetch('/api/actions/test-send-letter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outreach_id: outreachId, test_to: to }),
      })
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        throw new Error(j.error || `${r.status}`)
      }
      setTestState('queued')
    } catch (e: any) {
      setError(e.message || String(e))
      setTestState('error')
    }
  }

  if (!letter) return null

  return (
    <div className="flex flex-wrap gap-2 mt-3">
      <button
        onClick={onCopy}
        className="text-xs bg-neutral-200 text-neutral-800 rounded px-3 py-1.5 hover:bg-neutral-300"
      >
        {copyState === 'copied' ? '✓ Copied' : '📋 Copy letter'}
      </button>

      {testState === 'queued' ? (
        <span className="text-xs text-emerald-700 px-3 py-1.5">✓ test queued · check your inbox</span>
      ) : testState === 'sending' ? (
        <span className="text-xs text-neutral-500 px-3 py-1.5">…dispatching test</span>
      ) : (
        <button
          onClick={onTestSend}
          className="text-xs bg-amber-100 text-amber-800 rounded px-3 py-1.5 hover:bg-amber-200"
          title="Send to your own inbox first to preview"
        >
          🧪 Test send to me
        </button>
      )}

      {contactEmail ? (
        sendState === 'queued' ? (
          <span className="text-xs text-emerald-700 px-3 py-1.5">✓ send queued · check /pipeline</span>
        ) : sendState === 'sending' ? (
          <span className="text-xs text-neutral-500 px-3 py-1.5">…sending</span>
        ) : (
          <button
            onClick={onSend}
            className="text-xs bg-brand text-white rounded px-3 py-1.5 hover:opacity-90"
          >
            📧 Send via Gmail to {contactEmail}
          </button>
        )
      ) : (
        jobUrl && (
          <a
            href={jobUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs bg-blue-600 text-white rounded px-3 py-1.5 hover:opacity-90 inline-block"
          >
            🔗 Open apply page ↗
          </a>
        )
      )}

      {sendState === 'error' && (
        <span className="text-xs text-red-600 px-2 py-1.5">error: {error}</span>
      )}
    </div>
  )
}
