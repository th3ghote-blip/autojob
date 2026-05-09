import { cookies } from 'next/headers'

const COOKIE = 'autojob_owner'

export function isOwner(): boolean {
  return cookies().get(COOKIE)?.value === '1'
}

export function setOwnerCookie() {
  cookies().set(COOKIE, '1', {
    httpOnly: true, sameSite: 'lax', secure: true,
    maxAge: 60 * 60 * 24 * 30,
  })
}

export function clearOwnerCookie() {
  cookies().delete(COOKIE)
}

export function checkPassword(input: string): boolean {
  return !!process.env.APP_PASSWORD && input === process.env.APP_PASSWORD
}
