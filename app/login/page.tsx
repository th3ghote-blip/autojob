import { redirect } from 'next/navigation'
import { setOwnerCookie, checkPassword, isOwner } from '@/lib/auth'

async function login(formData: FormData) {
  'use server'
  const pw = String(formData.get('password') || '')
  if (checkPassword(pw)) {
    setOwnerCookie()
    redirect('/pipeline')
  }
  redirect('/login?error=1')
}

export default function LoginPage({ searchParams }: { searchParams: { error?: string } }) {
  if (isOwner()) redirect('/pipeline')
  return (
    <main className="min-h-screen grid place-items-center p-6">
      <form action={login} className="w-full max-w-sm bg-white/[0.04] border border-white/10 backdrop-blur-md rounded-2xl p-7 shadow-2xl shadow-violet-900/20 space-y-4">
        <div className="flex items-center gap-2">
          <div className="size-3 rounded-full bg-gradient-to-br from-violet-500 to-pink-500 shadow-[0_0_0_3px_rgba(99,102,241,0.18)]" />
          <h1 className="text-xl font-semibold tracking-tight text-slate-100">AutoJob</h1>
        </div>
        <p className="text-sm text-slate-400">Owner login.</p>
        <input
          name="password"
          type="password"
          autoFocus
          placeholder="Password"
          className="w-full rounded-md px-3 py-2"
        />
        {searchParams.error && <p className="text-sm text-rose-400">Wrong password.</p>}
        <button className="w-full bg-gradient-to-r from-violet-500 to-pink-500 text-white rounded-md py-2 font-medium shadow-lg shadow-violet-900/30 hover:opacity-90 transition-opacity">Sign in</button>
      </form>
    </main>
  )
}
