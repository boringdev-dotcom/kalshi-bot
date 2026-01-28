import { NavLink, Outlet } from 'react-router-dom';
import { Activity, TrendingUp, FlaskConical } from 'lucide-react';
import { clsx } from 'clsx';

export function Layout() {
  return (
    <div className="h-screen bg-bg-primary flex flex-col overflow-hidden">
      {/* Top Navigation Bar */}
      <header className="flex-none px-3 md:px-4 py-2 md:py-3 border-b border-border-subtle flex items-center justify-between">
        <div className="flex items-center gap-4 md:gap-6">
          <div className="flex items-center gap-2 md:gap-3">
            <Activity className="w-5 h-5 md:w-6 md:h-6 text-accent-blue" />
            <h1 className="text-base md:text-lg font-semibold text-text-primary">Kalshi</h1>
          </div>
          
          {/* Navigation Links */}
          <nav className="flex items-center gap-1">
            <NavLink
              to="/"
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-accent-blue/15 text-accent-blue'
                    : 'text-text-secondary hover:text-text-primary hover:bg-bg-secondary'
                )
              }
            >
              <TrendingUp className="w-4 h-4" />
              <span className="hidden sm:inline">Chart</span>
            </NavLink>
            <NavLink
              to="/research"
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-accent-blue/15 text-accent-blue'
                    : 'text-text-secondary hover:text-text-primary hover:bg-bg-secondary'
                )
              }
            >
              <FlaskConical className="w-4 h-4" />
              <span className="hidden sm:inline">Research</span>
            </NavLink>
          </nav>
        </div>
      </header>

      {/* Page Content */}
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
