import { redirect } from 'next/navigation'
import { isOwner } from '@/lib/auth'

export default function Home() {
  redirect(isOwner() ? '/pipeline' : '/login')
}
