import { NextRequest, NextResponse } from 'next/server'

// Defeat all caching for the share page so the recruiter (or you) never see
// a stale timeline. Every request hits the origin and gets fresh DB data.
export function middleware(req: NextRequest) {
  const res = NextResponse.next()
  if (req.nextUrl.pathname.startsWith('/share/')) {
    res.headers.set('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
    res.headers.set('Pragma', 'no-cache')
    res.headers.set('Expires', '0')
  }
  return res
}

export const config = {
  matcher: ['/share/:path*'],
}
