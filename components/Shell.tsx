import Link from 'next/link'

export default function Shell({ children, active }: { children: React.ReactNode; active?: string }) {
  const tabs = [
    { href: '/pipeline', label: 'Pipeline', key: 'pipeline' },
    { href: '/jobs', label: 'Jobs', key: 'jobs' },
    { href: '/sources', label: 'Sources', key: 'sources' },
  ]
  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-6">
          <Link href="/pipeline" className="font-semibold">AutoJob</Link>
          <nav className="flex gap-4 text-sm">
            {tabs.map((t) => (
              <Link
                key={t.key}
                href={t.href}
                className={
                  'px-2 py-1 rounded ' +
                  (active === t.key ? 'bg-neutral-100 font-medium' : 'text-neutral-600 hover:text-neutral-900')
                }
              >
                {t.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto text-xs text-neutral-500">info@getaiappgenius.com</div>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-6">{children}</main>
    </div>
  )
}
