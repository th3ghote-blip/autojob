import { createClient } from '@supabase/supabase-js'

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY

// Public-safe client used for read-only views with RLS-allowed access.
export const supabase = createClient(url, anonKey)

// Server-only client. Bypasses RLS. NEVER expose to client components.
export function supabaseAdmin() {
  if (!serviceKey) throw new Error('SUPABASE_SERVICE_ROLE_KEY is required server-side')
  return createClient(url, serviceKey, { auth: { persistSession: false } })
}
