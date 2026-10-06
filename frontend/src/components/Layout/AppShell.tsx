import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Footer } from './Footer'
import { ThemeToggle } from './ThemeToggle'

interface Props {
  children: ReactNode
}

export function AppShell({ children }: Props) {
  const { pathname } = useLocation()

  return (
    <div className="flex min-h-screen flex-col bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100">
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-2 flex items-center gap-6">
        <span className="font-semibold text-sm">Financial News Intelligence</span>
        <nav className="flex gap-4 text-sm ml-auto">
          <Link
            to="/"
            className={pathname === '/' ? 'font-semibold text-blue-600 dark:text-blue-400' : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100'}
          >
            Табло
          </Link>
          <Link
            to="/debug"
            className={pathname === '/debug' ? 'font-semibold text-blue-600 dark:text-blue-400' : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100'}
          >
            Debug
          </Link>
        </nav>
        <ThemeToggle />
      </header>
      <main className="flex-1">{children}</main>
      <Footer />
    </div>
  )
}
