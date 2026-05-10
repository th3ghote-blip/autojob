import Link from 'next/link'

export default function Shell({ children, active }: { children: React.ReactNode; active?: string }) {
  const tabs = [
    { href: '/pipeline', label: 'Pipeline', key: 'pipeline' },
    { href: '/jobs',     label: 'Jobs',     key: 'jobs' },
    { href: '/sources',  label: 'Sources',  key: 'sources' },
  ]
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-white/5 bg-slate-950/60 backdrop-blur-md sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-5 py-3 flex items-center gap-6">
          <Link href="/pipeline" className="flex items-center gap-2 group">
            <div className="size-2.5 rounded-full bg-gradient-to-br from-violet-500 to-pink-500 shadow-[0_0_0_3px_rgba(99,102,241,0.18)]" />
            <span className="font-semibold tracking-tight text-slate-100 group-hover:text-white transition-colors">
              AutoJob
            </span>
          </Link>
          <nav className="flex gap-1 text-sm">
            {tabs.map((t) => (
              <Link
                key={t.key}
                href={t.href}
                className={
                  'px-3 py-1.5 rounded-md transition-colors ' +
                  (active === t.key
                    ? 'bg-white/[0.06] text-white font-medium'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-white/[0.03]')
                }
              >
                {t.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto text-[11px] text-slate-500 tracking-wider uppercase">
            info@getaiappgenius.com
          </div>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto px-5 py-6">{children}</main>
    </div>
  )
}
