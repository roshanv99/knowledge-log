import { ExamIcon, FilmStripIcon, NotebookIcon, SlidersHorizontalIcon, type Icon } from '@phosphor-icons/react'
import { NavLink, Outlet } from 'react-router'

const items: { to: string; label: string; icon: Icon }[] = [
  { to: '/quiz', label: 'Quiz', icon: ExamIcon },
  { to: '/reels', label: 'Reels', icon: FilmStripIcon },
  { to: '/notes', label: 'Manage notes', icon: NotebookIcon },
  { to: '/settings', label: 'Settings', icon: SlidersHorizontalIcon },
]

// Phones: bottom tab bar. From 1024px: the same destinations in a side rail.
export function AppShell() {
  return (
    <div className="lg:grid lg:grid-cols-[240px_1fr]">
      <aside className="sticky top-0 hidden h-dvh flex-col border-r border-rule px-5 py-8 lg:flex">
        <p className="px-3 font-display text-[22px] leading-none font-semibold tracking-tight text-ink">
          Knowledge Log
        </p>
        <nav aria-label="Main" className="mt-10">
          <ul className="flex flex-col gap-1">
            {items.map(({ to, label, icon: ItemIcon }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] transition-colors ${
                      isActive ? 'bg-ink-soft font-bold text-ink' : 'text-muted hover:bg-ink-soft/50 hover:text-graphite'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <ItemIcon size={22} weight={isActive ? 'fill' : 'regular'} />
                      {label}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      <main className="min-h-dvh pb-[calc(76px+env(safe-area-inset-bottom))] lg:pb-0">
        <Outlet />
      </main>

      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-20 border-t border-rule bg-sheet pb-[env(safe-area-inset-bottom)] lg:hidden"
      >
        <ul className="grid grid-cols-4">
          {items.map(({ to, label, icon: ItemIcon }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  `flex h-[64px] flex-col items-center justify-center gap-1 text-center text-[12px] leading-tight ${
                    isActive ? 'font-bold text-ink' : 'text-muted'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <ItemIcon size={24} weight={isActive ? 'fill' : 'regular'} />
                    {label}
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  )
}
