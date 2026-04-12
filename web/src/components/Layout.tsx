import { NavLink, Outlet } from 'react-router-dom';
import { LayoutDashboard, Beer, BarChart3, Settings, Menu, X, Waves, MessageSquare, HelpCircle } from 'lucide-react';
import { useState } from 'react';
import ActivityFeed from './ActivityFeed';
import SlotToast from './SlotToast';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/portals', icon: Beer, label: 'Portals' },
  { to: '/statistics', icon: BarChart3, label: 'Statistics' },
  { to: '/settings', icon: Settings, label: 'Settings' },
  { to: '/welcome', icon: HelpCircle, label: 'Guide' },
];

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden bg-wiesn-cream">
      {/* Skip link */}
      <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:bg-wiesn-gold focus:text-wiesn-brown-dark focus:px-4 focus:py-2 focus:rounded-lg focus:text-sm focus:font-semibold">
        Skip to main content
      </a>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <button
          className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40 lg:hidden border-none cursor-default"
          aria-label="Close sidebar"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed lg:static inset-y-0 left-0 z-50 w-[260px] bg-wiesn-sidebar bavarian-pattern flex flex-col transform transition-transform duration-300 ease-in-out ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        {/* Logo */}
        <div className="px-6 py-7">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-wiesn-gold/20 flex items-center justify-center">
              <span className="text-2xl leading-none" aria-hidden="true">🍺</span>
            </div>
            <div>
              <h1 className="text-white font-bold text-[17px] tracking-tight leading-tight">
                Wiesn-Agent
              </h1>
              <p className="text-white/40 text-[11px] tracking-wide uppercase font-medium">
                Reservation Monitor
              </p>
            </div>
          </div>
        </div>

        {/* Divider */}
        <div className="mx-5 h-px bg-white/8" />

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2.5 rounded-xl text-[13px] font-medium transition-all duration-150 ${
                  isActive
                    ? 'bg-wiesn-gold/15 text-wiesn-gold-light shadow-sm shadow-wiesn-gold/10'
                    : 'text-white/55 hover:bg-white/6 hover:text-white/85'
                }`
              }
            >
              <Icon className="w-[18px] h-[18px]" strokeWidth={1.8} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-5 py-5">
          <button
            onClick={() => setActivityOpen(!activityOpen)}
            aria-expanded={activityOpen}
            aria-controls="chat-panel"
            className={`flex items-center gap-2 w-full px-4 py-2.5 rounded-xl text-[13px] font-medium transition-colors duration-150 ${
              activityOpen
                ? 'bg-wiesn-gold/15 text-wiesn-gold-light'
                : 'text-white/55 hover:bg-white/6 hover:text-white/85'
            }`}
          >
            <MessageSquare className="w-[18px] h-[18px]" strokeWidth={1.8} aria-hidden="true" />
            Chat
          </button>
          <div className="flex items-center gap-2 text-white/25 mt-3">
            <Waves className="w-3.5 h-3.5" aria-hidden="true" />
            <p className="text-[10px] tracking-wider uppercase font-medium">
              Oktoberfest 2026
            </p>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile header */}
        <header className="lg:hidden flex items-center gap-3 px-4 py-3 bg-wiesn-sidebar/95 backdrop-blur-md text-white border-b border-white/5">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 hover:bg-white/10 rounded-lg transition-colors"
            aria-label={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
          >
            {sidebarOpen ? <X className="w-5 h-5" aria-hidden="true" /> : <Menu className="w-5 h-5" aria-hidden="true" />}
          </button>
          <div className="flex items-center gap-2">
            <span className="text-lg">🍺</span>
            <span className="font-semibold text-sm tracking-tight">Wiesn-Agent</span>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto" id="main-content">
          <div className="p-5 lg:p-8 max-w-[1400px]">
            <Outlet />
          </div>
        </main>
      </div>

      {/* Activity Feed Panel */}
      <ActivityFeed open={activityOpen} onClose={() => setActivityOpen(false)} />

      {/* Slot alert toasts + browser notifications */}
      <SlotToast />

      {/* Mobile activity FAB */}
      {!activityOpen && (
        <button
          onClick={() => setActivityOpen(true)}
          className="fixed bottom-4 right-4 lg:hidden w-12 h-12 rounded-full bg-wiesn-blue shadow-lg flex items-center justify-center text-white z-40"
          aria-label="Open chat"
        >
          <MessageSquare className="w-5 h-5" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
