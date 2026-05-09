import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AutoJob',
  description: 'AI agent that finds AI/high-paying jobs and writes personalised outreach.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
