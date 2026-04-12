import { MessageSquare, ArrowRight, TentTree } from 'lucide-react';
import { Link } from 'react-router-dom';

const STEPS = [
  {
    emoji: '⚙️',
    title: '1. Configure',
    desc: 'Enter your details, preferred dates, and notification channels in Settings.',
    color: 'bg-wiesn-blue/10',
  },
  {
    emoji: '🎪',
    title: '2. Choose Tents',
    desc: 'Enable the beer tents you want to monitor on the Portals page. All 38 tents are pre-configured.',
    color: 'bg-wiesn-gold/10',
  },
  {
    emoji: '🔍',
    title: '3. Scan',
    desc: 'Hit "Scan Now" on the Dashboard or let the background scanner check every 30 minutes automatically.',
    color: 'bg-wiesn-success/10',
  },
  {
    emoji: '🍺',
    title: '4. Book',
    desc: 'When slots are found, ask the chat agent to pre-fill the form. You always confirm the final submit.',
    color: 'bg-wiesn-brown/10',
  },
];

const FEATURES = [
  {
    emoji: '🏕️',
    title: '38 Beer Tents',
    desc: 'All official Oktoberfest tents pre-configured — große and kleine Zelte.',
  },
  {
    emoji: '🤖',
    title: 'AI Chat Assistant',
    desc: 'Ask questions in natural language — the agent scans portals and answers. Requires a GITHUB_TOKEN for full AI chat.',
  },
  {
    emoji: '⏰',
    title: 'Auto-Monitoring',
    desc: 'Background scanner checks every 30 min. Sends push notifications when new evening slots are detected.',
  },
  {
    emoji: '📲',
    title: '130+ Notification Channels',
    desc: 'ntfy (free push), Telegram, Slack, Email, Discord, WhatsApp and more — powered by Apprise.',
  },
  {
    emoji: '🛡️',
    title: 'Human-in-the-Loop',
    desc: 'Forms are never auto-submitted. The agent pre-fills, you review and click submit.',
  },
  {
    emoji: '🌙',
    title: 'Smart Slot Detection',
    desc: 'Deep-scans time slots for your preferred dates — morning ☀️, afternoon 🌤️, or evening 🌙.',
  },
];

const CHAT_EXAMPLES = [
  { emoji: '🌙', text: 'Are there evening slots on September 25th?' },
  { emoji: '📋', text: 'Which tents have open reservations right now?' },
  { emoji: '📝', text: 'Fill the reservation form for Kufflers Weinzelt' },
  { emoji: '📊', text: 'What is the current status of all portals?' },
];

export default function Welcome() {
  return (
    <div className="space-y-8 animate-fade-in motion-reduce:animate-none">
      {/* Hero */}
      <div className="relative overflow-hidden bg-gradient-to-br from-wiesn-blue via-wiesn-blue-dark to-wiesn-sidebar rounded-2xl p-8 sm:p-10 text-white">
        <div className="absolute top-0 right-0 w-64 h-64 bg-wiesn-gold/10 rounded-full -translate-y-1/2 translate-x-1/3 blur-3xl" />
        <div className="absolute -bottom-8 -left-8 w-40 h-40 bg-wiesn-blue-light/15 rounded-full blur-3xl" />
        <div className="absolute top-6 right-8 text-[100px] opacity-[0.07] leading-none select-none pointer-events-none" aria-hidden="true">
          🍺
        </div>
        <div className="relative">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-4xl" role="img" aria-label="Beer">🍺</span>
            <div>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">Wiesn-Agent</h1>
              <p className="text-wiesn-gold-light/80 text-sm font-medium mt-0.5">AI-powered Oktoberfest Reservations</p>
            </div>
          </div>
          <p className="text-white/80 text-lg max-w-2xl leading-relaxed mt-2">
            Monitors <strong className="text-white">38 beer tent portals</strong>, alerts you when slots open up,
            and helps you book before anyone else. 🎯
          </p>
          <div className="flex flex-wrap gap-3 mt-7">
            <Link
              to="/settings"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-wiesn-gold text-wiesn-brown-dark font-semibold rounded-xl hover:bg-wiesn-gold-light transition-colors shadow-lg shadow-wiesn-gold/20 hover:-translate-y-px"
            >
              ⚙️ Configure First
            </Link>
            <Link
              to="/portals"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-white/15 text-white font-medium rounded-xl hover:bg-white/25 transition-colors backdrop-blur-sm"
            >
              <TentTree className="w-4 h-4" aria-hidden="true" />
              Choose Tents
            </Link>
            <Link
              to="/"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-white/10 text-white font-medium rounded-xl hover:bg-white/20 transition-colors backdrop-blur-sm"
            >
              Go to Dashboard
              <ArrowRight className="w-4 h-4" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </div>

      {/* How It Works */}
      <section>
        <h2 className="text-xl font-bold text-wiesn-brown-dark mb-4">📖 How It Works</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {STEPS.map((step, i) => (
            <div
              key={step.title}
              className="relative bg-white border border-wiesn-border-light rounded-2xl p-5 hover:shadow-md hover:-translate-y-0.5 transition-all group"
            >
              {i < STEPS.length - 1 && (
                <div className="hidden lg:block absolute top-1/2 -right-3 text-wiesn-border text-lg" aria-hidden="true">→</div>
              )}
              <div className={`w-12 h-12 rounded-xl ${step.color} flex items-center justify-center mb-3`}>
                <span className="text-2xl" role="img" aria-hidden="true">{step.emoji}</span>
              </div>
              <h3 className="font-semibold text-wiesn-brown-dark text-sm mb-1">{step.title}</h3>
              <p className="text-wiesn-text-light text-[13px] leading-relaxed">{step.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section>
        <h2 className="text-xl font-bold text-wiesn-brown-dark mb-4">✨ Features</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="bg-white border border-wiesn-border-light rounded-2xl p-5 hover:shadow-md hover:-translate-y-0.5 transition-all"
            >
              <div className="flex items-center gap-2.5 mb-2">
                <span className="text-xl" role="img" aria-hidden="true">{f.emoji}</span>
                <h3 className="font-semibold text-wiesn-brown-dark text-sm">{f.title}</h3>
              </div>
              <p className="text-wiesn-text-light text-[13px] leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Chat Examples */}
      <section className="bg-white border border-wiesn-border-light rounded-2xl p-6">
        <div className="flex items-center gap-2.5 mb-4">
          <MessageSquare className="w-5 h-5 text-wiesn-blue" aria-hidden="true" />
          <h2 className="text-lg font-bold text-wiesn-brown-dark">💬 Try These in Chat</h2>
        </div>
        <p className="text-wiesn-text-light text-sm mb-4">
          Open Chat from the sidebar or the mobile chat button and try these prompts:
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {CHAT_EXAMPLES.map((ex) => (
            <div
              key={ex.text}
              className="flex items-start gap-3 px-4 py-3 bg-wiesn-cream/60 border border-wiesn-border-light rounded-xl hover:bg-wiesn-cream transition-colors"
            >
              <span className="text-base mt-0.5" role="img" aria-hidden="true">{ex.emoji}</span>
              <span className="text-[13px] text-wiesn-text leading-relaxed italic">"{ex.text}"</span>
            </div>
          ))}
        </div>
      </section>

      {/* Quick Tips */}
      <section className="bg-gradient-to-r from-wiesn-gold/5 to-wiesn-gold/10 border border-wiesn-gold/20 rounded-2xl p-6">
        <h2 className="text-lg font-bold text-wiesn-brown-dark mb-3">💡 Quick Tips</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="flex items-start gap-2.5">
            <span className="text-base" aria-hidden="true">📅</span>
            <p className="text-[13px] text-wiesn-text-light leading-relaxed">
              Most tents open reservations <strong className="text-wiesn-brown-dark">~3 months before Oktoberfest</strong> (around mid-June).
            </p>
          </div>
          <div className="flex items-start gap-2.5">
            <span className="text-base" aria-hidden="true">🌙</span>
            <p className="text-[13px] text-wiesn-text-light leading-relaxed">
              <strong className="text-wiesn-brown-dark">Evening slots</strong> (16:00–23:00) are the most popular and go fast!
            </p>
          </div>
          <div className="flex items-start gap-2.5">
            <span className="text-base" aria-hidden="true">🔔</span>
            <p className="text-[13px] text-wiesn-text-light leading-relaxed">
              Get <strong className="text-wiesn-brown-dark">phone push notifications</strong> free: install the{' '}
              <a href="https://ntfy.sh" target="_blank" rel="noopener noreferrer" className="text-wiesn-blue underline underline-offset-2">ntfy app</a>
              {' '}({' '}
              <a href="https://apps.apple.com/app/ntfy/id1625396347" target="_blank" rel="noopener noreferrer" className="text-wiesn-blue underline underline-offset-2">iOS</a>
              {' / '}
              <a href="https://play.google.com/store/apps/details?id=io.heckel.ntfy" target="_blank" rel="noopener noreferrer" className="text-wiesn-blue underline underline-offset-2">Android</a>
              {' '}) → subscribe to your channel name → add <code className="bg-wiesn-cream px-1 rounded text-[11px]">ntfy://your-channel</code> in Settings.
            </p>
          </div>
          <div className="flex items-start gap-2.5">
            <span className="text-base" aria-hidden="true">🏆</span>
            <p className="text-[13px] text-wiesn-text-light leading-relaxed">
              <strong className="text-wiesn-brown-dark">Saturday evenings</strong> and German Unity Day (Oct 3) are hardest to get.
            </p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <div className="text-center pb-4">
        <p className="text-sm text-wiesn-text-muted">
          🍻 You can always find this guide under "Guide" in the sidebar. Prost!
        </p>
      </div>
    </div>
  );
}
