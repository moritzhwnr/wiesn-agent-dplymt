import { useEffect, useState } from 'react';
import { Save, Plus, X, Bell, Clock, User, Monitor, Camera, CalendarDays, Info } from 'lucide-react';
import { api } from '../api';
import type { Config } from '../api';

function formatDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  return new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' }).format(d);
}

function Toggle({ on, onToggle, disabled }: { on: boolean; onToggle: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onToggle}
      disabled={disabled}
      className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out cursor-pointer focus:outline-none focus:ring-2 focus:ring-wiesn-gold/30 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed ${
        on ? 'bg-wiesn-success' : 'bg-gray-300'
      }`}
    >
      <span
        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
          on ? 'translate-x-5' : 'translate-x-0'
        }`}
      />
    </button>
  );
}

function SectionHint({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 mb-5 p-3 bg-wiesn-blue/4 border border-wiesn-blue/10 rounded-xl">
      <Info className="w-4 h-4 text-wiesn-blue/60 mt-0.5 flex-shrink-0" />
      <p className="text-[12px] text-wiesn-text-light leading-relaxed">{children}</p>
    </div>
  );
}

export default function Settings() {
  const [config, setConfig] = useState<Config | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [newDay, setNewDay] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [dirty, setDirty] = useState(false);
  // Track which apprise_urls were explicitly added/removed by the user
  // to avoid round-tripping redacted "ntfy://***" values back to the backend
  const [appriseUrlsChanged, setAppriseUrlsChanged] = useState(false);
  // Store the user's actual apprise_urls edits (not the redacted server values)
  const [localAppriseUrls, setLocalAppriseUrls] = useState<string[]>([]);

  useEffect(() => {
    api.getConfig().then((c) => {
      setConfig(c);
      setLocalAppriseUrls(c.notifications.apprise_urls);
    }).catch((e) => setError(e.message));
  }, []);

  // Warn before navigating away with unsaved changes
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  const markDirty = () => { setDirty(true); setSaved(false); };

  const save = async () => {
    if (!config) return;
    setSaving(true);
    setSaved(false);
    setError('');
    try {
      // Build update payload — exclude apprise_urls unless explicitly changed
      // to avoid overwriting real secrets with redacted "ntfy://***" values
      const payload: Partial<Config> = {
        user: config.user,
        reservierung: config.reservierung,
        monitoring: config.monitoring,
        notifications: {
          ...config.notifications,
          apprise_urls: appriseUrlsChanged ? localAppriseUrls : config.notifications.apprise_urls,
        },
      };
      // If apprise_urls weren't changed, strip them from the update
      if (!appriseUrlsChanged) {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { apprise_urls: _, ...notifWithout } = payload.notifications!;
        payload.notifications = notifWithout as Config['notifications'];
      }
      const updated = await api.updateConfig(payload);
      setConfig(updated);
      setLocalAppriseUrls(updated.notifications.apprise_urls);
      setAppriseUrlsChanged(false);
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 4000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const updateUser = (field: string, value: string | number) => {
    markDirty();
    setConfig((c) => c ? { ...c, user: { ...c.user, [field]: value } } : c);
  };

  const updateMonitoring = (field: string, value: number | boolean) => {
    markDirty();
    setConfig((c) => c ? { ...c, monitoring: { ...c.monitoring, [field]: value } } : c);
  };

  const updateSlot = (slot: 'morgens' | 'mittags' | 'abends', field: string, value: string | boolean | number) => {
    markDirty();
    setConfig((c) => c ? {
      ...c,
      reservierung: {
        ...c.reservierung,
        slots: {
          ...c.reservierung.slots,
          [slot]: { ...c.reservierung.slots[slot], [field]: value },
        },
      },
    } : c);
  };

  const addDay = () => {
    if (!newDay || !config) return;
    if (config.reservierung.wunsch_tage.includes(newDay)) return;
    markDirty();
    setConfig({
      ...config,
      reservierung: {
        ...config.reservierung,
        wunsch_tage: [...config.reservierung.wunsch_tage, newDay].sort(),
      },
    });
    setNewDay('');
  };

  const removeDay = (day: string) => {
    if (!config) return;
    markDirty();
    setConfig({
      ...config,
      reservierung: {
        ...config.reservierung,
        wunsch_tage: config.reservierung.wunsch_tage.filter((d) => d !== day),
      },
    });
  };

  const addAppriseUrl = () => {
    if (!newUrl.trim() || !config) return;
    markDirty();
    setAppriseUrlsChanged(true);
    const updated = [...localAppriseUrls, newUrl.trim()];
    setLocalAppriseUrls(updated);
    setConfig({
      ...config,
      notifications: {
        ...config.notifications,
        apprise_urls: updated,
      },
    });
    setNewUrl('');
  };

  const removeAppriseUrl = (url: string) => {
    if (!config) return;
    markDirty();
    setAppriseUrlsChanged(true);
    const updated = localAppriseUrls.filter((u) => u !== url);
    setLocalAppriseUrls(updated);
    setConfig({
      ...config,
      notifications: {
        ...config.notifications,
        apprise_urls: updated,
      },
    });
  };

  if (!config) {
    return (
      <div className="flex items-center justify-center h-64 text-wiesn-text-muted">
        {error ? `Error: ${error}` : 'Loading settings…'}
      </div>
    );
  }

  const inputCls = 'w-full px-3.5 py-2.5 bg-white border border-wiesn-border-light rounded-xl text-sm text-wiesn-text placeholder:text-wiesn-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-wiesn-gold/30 focus-visible:border-wiesn-gold/50 transition-colors';
  const labelCls = 'block text-[13px] font-medium text-wiesn-brown-dark mb-1.5';
  const hintCls = 'text-[11px] text-wiesn-text-muted mt-1.5';

  const slotInfo: Record<string, { label: string; icon: string; desc: string }> = {
    morgens: { label: 'Morning', icon: '☀️', desc: '10:00 – 12:00' },
    mittags: { label: 'Afternoon', icon: '🌤️', desc: '12:00 – 16:00' },
    abends: { label: 'Evening', icon: '🌙', desc: '16:00 – 23:00' },
  };

  return (
    <div className="space-y-6 max-w-4xl pb-24">
      {/* Header */}
      <div className="animate-fade-in">
        <h1 className="text-2xl font-bold text-wiesn-brown-dark tracking-tight">
          Settings
        </h1>
        <p className="text-wiesn-text-light text-sm mt-1 leading-relaxed">
          Configure your reservation details, preferred dates, and notifications.
        </p>
      </div>

      {error && (
        <div className="bg-wiesn-error/5 border border-wiesn-error/20 text-wiesn-error rounded-xl px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {/* ── Persönliche Daten ── */}
      <section className="bg-white border border-wiesn-border-light rounded-2xl p-6 animate-fade-in animate-fade-in-delay-1">
        <div className="flex items-center gap-2.5 mb-2">
          <div className="w-8 h-8 rounded-lg bg-wiesn-blue/8 flex items-center justify-center">
            <User className="w-4 h-4 text-wiesn-blue" />
          </div>
          <h2 className="text-[15px] font-semibold text-wiesn-brown-dark tracking-tight">
            Personal Details
          </h2>
        </div>
        <SectionHint>
          This data is used when automatically filling out reservation forms.
        </SectionHint>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="vorname" className={labelCls}>First Name</label>
            <input id="vorname" name="vorname" className={inputCls} autoComplete="given-name" value={config.user.vorname} onChange={(e) => updateUser('vorname', e.target.value)} />
          </div>
          <div>
            <label htmlFor="nachname" className={labelCls}>Last Name</label>
            <input id="nachname" name="nachname" className={inputCls} autoComplete="family-name" value={config.user.nachname} onChange={(e) => updateUser('nachname', e.target.value)} />
          </div>
          <div>
            <label htmlFor="email" className={labelCls}>Email</label>
            <input id="email" name="email" className={inputCls} type="email" autoComplete="email" spellCheck={false} value={config.user.email} onChange={(e) => updateUser('email', e.target.value)} />
            <p className={hintCls}>Used for reservation confirmation</p>
          </div>
          <div>
            <label htmlFor="telefon" className={labelCls}>Phone</label>
            <input id="telefon" name="telefon" className={inputCls} type="tel" autoComplete="tel" placeholder="+49 170 1234567…" value={config.user.telefon} onChange={(e) => updateUser('telefon', e.target.value)} />
          </div>
          <div>
            <label htmlFor="personen" className={labelCls}>Group size (persons)</label>
            <input id="personen" name="personen" className={inputCls} type="number" inputMode="numeric" min={1} max={20} value={config.user.personen} onChange={(e) => updateUser('personen', parseInt(e.target.value) || 1)} />
            <p className={hintCls}>How many people would you like to register?</p>
          </div>
          <div>
            <label htmlFor="notizen" className={labelCls}>Additional notes</label>
            <input id="notizen" name="notizen" className={inputCls} placeholder="Stroller, wheelchair…" value={config.user.notizen} onChange={(e) => updateUser('notizen', e.target.value)} />
            <p className={hintCls}>Optional — entered in free-text fields</p>
          </div>
        </div>
      </section>

      {/* ── Wunsch-Tage ── */}
      <section className="bg-white border border-wiesn-border-light rounded-2xl p-6 animate-fade-in animate-fade-in-delay-2">
        <div className="flex items-center gap-2.5 mb-2">
          <div className="w-8 h-8 rounded-lg bg-wiesn-gold/10 flex items-center justify-center">
            <CalendarDays className="w-4 h-4 text-wiesn-gold" />
          </div>
          <h2 className="text-[15px] font-semibold text-wiesn-brown-dark tracking-tight">
            Preferred Dates
          </h2>
        </div>
        <SectionHint>
          Which days would you like to go to the Wiesn? The agent specifically searches for
          available reservations on these dates (Oktoberfest 2026: Sep 19 – Oct 4).
        </SectionHint>
        <div className="flex flex-wrap gap-2 mb-4">
          {config.reservierung.wunsch_tage.length === 0 && (
            <span className="text-sm text-wiesn-text-muted italic">No dates selected yet</span>
          )}
          {config.reservierung.wunsch_tage.map((day) => (
            <span
              key={day}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-wiesn-gold/10 text-wiesn-brown rounded-lg text-[13px] font-medium"
            >
              {formatDate(day)}
              <button
                onClick={() => removeDay(day)}
                className="hover:text-wiesn-error transition-colors rounded-md hover:bg-wiesn-error/10 p-0.5"
                aria-label={`Remove ${formatDate(day)}`}
              >
                <X className="w-3.5 h-3.5" aria-hidden="true" />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <label className={labelCls}>Add new date</label>
            <input
              className={inputCls}
              type="date"
              min="2026-09-19"
              max="2026-10-04"
              value={newDay}
              onChange={(e) => setNewDay(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addDay()}
            />
          </div>
          <button
            onClick={addDay}
            disabled={!newDay}
            className="px-4 py-2.5 bg-wiesn-gold/15 text-wiesn-gold-dark rounded-xl text-sm font-medium hover:bg-wiesn-gold/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" />
            Add
          </button>
        </div>
      </section>

      {/* ── Zeitfenster ── */}
      <section className="bg-white border border-wiesn-border-light rounded-2xl p-6 animate-fade-in animate-fade-in-delay-3">
        <div className="flex items-center gap-2.5 mb-2">
          <div className="w-8 h-8 rounded-lg bg-wiesn-blue/8 flex items-center justify-center">
            <Clock className="w-4 h-4 text-wiesn-blue" />
          </div>
          <h2 className="text-[15px] font-semibold text-wiesn-brown-dark tracking-tight">
            Preferred Time Slots
          </h2>
        </div>
        <SectionHint>
          Enable the time periods you'd like to reserve. Priority 1 = highest
          priority. With multiple active time slots, the one with the highest priority is checked first.
        </SectionHint>
        <div className="space-y-3">
          {(Object.keys(slotInfo) as Array<'morgens' | 'mittags' | 'abends'>).map((slot) => {
            const info = slotInfo[slot];
            const s = config.reservierung.slots[slot];
            return (
              <div
                key={slot}
                className={`rounded-xl border transition-all duration-200 ${
                  s.enabled
                    ? 'border-wiesn-gold/30 bg-wiesn-gold/4'
                    : 'border-wiesn-border-light bg-white opacity-50'
                }`}
              >
                <div className="flex items-center justify-between p-4">
                  <div className="flex items-center gap-3">
                    <Toggle on={s.enabled} onToggle={() => updateSlot(slot, 'enabled', !s.enabled)} />
                    <div>
                      <span className="font-medium text-[13px] text-wiesn-brown-dark">
                        {info.icon} {info.label}
                      </span>
                      <span className="text-[11px] text-wiesn-text-muted ml-2">
                        ({info.desc})
                      </span>
                    </div>
                  </div>
                  {s.enabled && (
                    <div className="flex items-center gap-1 text-[11px] bg-wiesn-gold/15 px-2.5 py-1 rounded-lg">
                      <span className="text-wiesn-gold-dark font-medium">Priority {s.prioritaet}</span>
                    </div>
                  )}
                </div>
                {s.enabled && (
                  <div className="px-4 pb-4 flex flex-wrap items-center gap-3 border-t border-wiesn-border-light/50 pt-3">
                    <div className="flex items-center gap-2 text-sm">
                      <label className="text-wiesn-text-muted text-[12px]">From:</label>
                      <input
                        className="px-2.5 py-1.5 bg-white border border-wiesn-border-light rounded-lg text-sm w-28 focus:outline-none focus:ring-2 focus:ring-wiesn-gold/30"
                        type="time"
                        value={s.von}
                        onChange={(e) => updateSlot(slot, 'von', e.target.value)}
                      />
                    </div>
                    <div className="flex items-center gap-2 text-sm">
                      <label className="text-wiesn-text-muted text-[12px]">To:</label>
                      <input
                        className="px-2.5 py-1.5 bg-white border border-wiesn-border-light rounded-lg text-sm w-28 focus:outline-none focus:ring-2 focus:ring-wiesn-gold/30"
                        type="time"
                        value={s.bis}
                        onChange={(e) => updateSlot(slot, 'bis', e.target.value)}
                      />
                    </div>
                    <div className="flex items-center gap-2 text-sm">
                      <label className="text-wiesn-text-muted text-[12px]">Priority:</label>
                      <select
                        className="px-2.5 py-1.5 bg-white border border-wiesn-border-light rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-wiesn-gold/30"
                        value={s.prioritaet}
                        onChange={(e) => updateSlot(slot, 'prioritaet', parseInt(e.target.value))}
                      >
                        <option value={1}>1 — Highest</option>
                        <option value={2}>2 — High</option>
                        <option value={3}>3 — Normal</option>
                      </select>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Scan-Einstellungen ── */}
      <section className="bg-white border border-wiesn-border-light rounded-2xl p-6 animate-fade-in animate-fade-in-delay-4">
        <div className="flex items-center gap-2.5 mb-2">
          <div className="w-8 h-8 rounded-lg bg-wiesn-blue/8 flex items-center justify-center">
            <Monitor className="w-4 h-4 text-wiesn-blue" />
          </div>
          <h2 className="text-[15px] font-semibold text-wiesn-brown-dark tracking-tight">
            Scan Settings
          </h2>
        </div>
        <SectionHint>
          Control how often the agent checks the reservation portals. More frequent scans detect
          new dates faster, but generate more network traffic.
        </SectionHint>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <div>
            <label className={labelCls}>Scan interval (minutes)</label>
            <div className="flex items-center gap-3">
              <input
                className="w-full h-2 bg-wiesn-border-light rounded-full appearance-none cursor-pointer accent-wiesn-gold"
                type="range"
                min={5}
                max={180}
                step={5}
                value={config.monitoring.check_interval_minutes}
                onChange={(e) => updateMonitoring('check_interval_minutes', parseInt(e.target.value))}
              />
              <span className="text-sm font-semibold text-wiesn-brown-dark min-w-[60px] text-right tabular-nums">
                {config.monitoring.check_interval_minutes} min
              </span>
            </div>
            <p className={hintCls}>
              {config.monitoring.check_interval_minutes <= 15
                ? '⚡ Very frequent — fast detection'
                : config.monitoring.check_interval_minutes <= 60
                  ? '✅ Recommended — good balance'
                  : '🐢 Infrequent — less traffic'}
            </p>
          </div>
          <div>
            <label className={labelCls}>Screenshot on changes</label>
            <div className="flex items-center gap-3 mt-2">
              <Toggle
                on={config.monitoring.screenshot_on_change}
                onToggle={() => updateMonitoring('screenshot_on_change', !config.monitoring.screenshot_on_change)}
              />
              <span className="text-[13px] text-wiesn-text-light">
                {config.monitoring.screenshot_on_change
                  ? 'Active — saves screenshots'
                  : 'Disabled'}
              </span>
            </div>
            <p className={hintCls}>
              <Camera className="w-3 h-3 inline mr-1" />
              Screenshots help with tracking
            </p>
          </div>
        </div>
      </section>

      {/* ── Benachrichtigungen ── */}
      <section className="bg-white border border-wiesn-border-light rounded-2xl p-6 animate-fade-in animate-fade-in-delay-4">
        <div className="flex items-center gap-2.5 mb-2">
          <div className="w-8 h-8 rounded-lg bg-wiesn-gold/10 flex items-center justify-center">
            <Bell className="w-4 h-4 text-wiesn-gold" />
          </div>
          <h2 className="text-[15px] font-semibold text-wiesn-brown-dark tracking-tight">
            Notifications
          </h2>
        </div>
        <SectionHint>
          Get notified immediately when new reservation dates become available.
          You can use multiple notification channels simultaneously.
        </SectionHint>

        <div className="flex items-center gap-3 mb-5 p-3.5 bg-wiesn-cream/60 border border-wiesn-border-light rounded-xl">
          <Toggle
            on={config.notifications.desktop}
            onToggle={() => {
              markDirty();
              setConfig((c) =>
                c ? { ...c, notifications: { ...c.notifications, desktop: !c.notifications.desktop } } : c
              );
            }}
          />
          <div>
            <span className="text-[13px] font-medium text-wiesn-brown-dark">
              Desktop notifications
            </span>
            <p className="text-[11px] text-wiesn-text-muted">System notifications on your computer</p>
          </div>
        </div>

        <div>
          <label className={labelCls}>Push notifications (Apprise)</label>
          <p className="text-[11px] text-wiesn-text-muted mb-3 leading-relaxed">
            Add services —
            e.g. <code className="bg-wiesn-cream px-1.5 py-0.5 rounded-md text-[11px]">ntfy://channel</code>,{' '}
            <code className="bg-wiesn-cream px-1.5 py-0.5 rounded-md text-[11px]">tgram://bottoken/chat</code>,{' '}
            <code className="bg-wiesn-cream px-1.5 py-0.5 rounded-md text-[11px]">slack://token/channel</code>
          </p>
          <div className="space-y-2 mb-3">
            {config.notifications.apprise_urls.length === 0 && (
              <p className="text-sm text-wiesn-text-muted italic py-2">
                No push services configured
              </p>
            )}
            {config.notifications.apprise_urls.map((url, i) => (
              <div
                key={`${url}-${i}`}
                className="flex items-center justify-between gap-2 px-3.5 py-2.5 bg-wiesn-cream/50 border border-wiesn-border-light rounded-xl group"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Bell className="w-3.5 h-3.5 text-wiesn-gold flex-shrink-0" />
                  <code className="text-[13px] text-wiesn-text truncate">{url}</code>
                </div>
                <button
                  onClick={() => removeAppriseUrl(url)}
                  className="text-wiesn-text-muted hover:text-wiesn-error flex-shrink-0 transition-colors p-1 rounded-lg hover:bg-wiesn-error/10"
                  aria-label={`Remove notification service`}
                >
                  <X className="w-4 h-4" aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              className={inputCls}
              name="apprise-url"
              type="url"
              autoComplete="off"
              spellCheck={false}
              placeholder="ntfy://my-channel…"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addAppriseUrl()}
              aria-label="Notification service URL"
            />
            <button
              onClick={addAppriseUrl}
              disabled={!newUrl.trim()}
              className="px-4 py-2.5 bg-wiesn-gold/15 text-wiesn-gold-dark rounded-xl text-sm font-medium hover:bg-wiesn-gold/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
            >
              <Plus className="w-4 h-4" />
              Add
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3 mt-5 p-3.5 bg-wiesn-cream/60 border border-wiesn-border-light rounded-xl">
          <Toggle
            on={config.notifications.use_emojis}
            onToggle={() => {
              markDirty();
              setConfig((c) =>
                c ? { ...c, notifications: { ...c.notifications, use_emojis: !c.notifications.use_emojis } } : c
              );
            }}
          />
          <div>
            <span className="text-[13px] font-medium text-wiesn-brown-dark">
              Fun emojis 🍺🌙🎪
            </span>
            <p className="text-[11px] text-wiesn-text-muted">Add festive emojis to notification titles</p>
          </div>
        </div>
      </section>

      {/* ── Sticky Save Bar ── */}
      <div className={`fixed bottom-0 left-0 right-0 z-50 transition-all duration-300 ${dirty || saved ? 'translate-y-0' : 'translate-y-full'}`}>
        <div className="bg-white/90 backdrop-blur-lg border-t border-wiesn-border-light shadow-lg">
          <div className="max-w-4xl mx-auto px-6 py-3.5 flex items-center justify-between">
            <span className="text-[13px] text-wiesn-text-light">
              {saved ? '✅ Changes saved!' : dirty ? 'Unsaved changes' : ''}
            </span>
            <button
              onClick={save}
              disabled={saving || (!dirty && !saved)}
              className={`inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-medium text-sm transition-all duration-200 ${
                saved
                  ? 'bg-wiesn-success text-white shadow-md shadow-wiesn-success/20'
                  : dirty
                    ? 'bg-wiesn-blue text-white hover:bg-wiesn-blue-light shadow-lg shadow-wiesn-blue/20 hover:-translate-y-px'
                    : 'bg-gray-200 text-gray-400 cursor-not-allowed'
              } disabled:opacity-50`}
            >
              <Save className="w-4 h-4" />
              {saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
