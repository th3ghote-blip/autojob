import { createClient, SupabaseClient } from '@supabase/supabase-js'

// Lazy clients so missing env vars don't blow up at build time during
// Next's page-data collection (Vercel may build before secrets land).

let _public: SupabaseClient | null = null
let _admin: SupabaseClient | null = null

export function supabase(): SupabaseClient {
  if (_public) return _public
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  if (!url || !anonKey) {
    throw new Error('Supabase env vars missing: NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY')
  }
  _public = createClient(url, anonKey)
  return _public
}

export function supabaseAdmin(): SupabaseClient {
  if (_admin) return _admin
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!url || !key) {
    throw new Error('Supabase admin env vars missing: NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY')
  }
  _admin = createClient(url, key, { auth: { persistSession: false } })
  return _admin
}
