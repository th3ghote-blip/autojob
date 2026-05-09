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
      <form action={login} className="w-full max-w-sm bg-white border rounded-lg p-6 shadow-sm space-y-4">
        <h1 className="text-xl font-semibold">AutoJob</h1>
        <p className="text-sm text-neutral-500">Owner login.</p>
        <input
          name="password"
          type="password"
          autoFocus
          placeholder="Password"
          className="w-full border rounded px-3 py-2"
        />
        {searchParams.error && <p className="text-sm text-red-600">Wrong password.</p>}
        <button className="w-full bg-brand text-white rounded py-2 font-medium">Sign in</button>
      </form>
    </main>
  )
}
