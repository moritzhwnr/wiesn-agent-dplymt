import { useEffect, useState, useMemo, useCallback } from 'react';
import { Beer, Calendar, RefreshCw, ArrowRight, CheckCircle, XCircle, Clock, Zap, ExternalLink, TentTree } from 'lucide-react';
import { useNavigate, Link } from 'react-router-dom';
import { api } from '../api';
import type { Summary, Portal, Config } from '../api';

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hrs ago`;
  return `${Math.floor(hrs / 24)} days ago`;
}

function formatDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  return new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short' }).format(d);
}

export default function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [portals, setPortals] = useState<Portal[]>([]);
  const [config, setConfig] = useState<Config | null>(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const load = useCallback(() => {
    Promise.all([api.getSummary(), api.getPortals(), api.getConfig()])
      .then(([s, p, c]) => {
        setSummary(s);
        setPortals(p);
        setConfig(c);
        setError('');
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load]);

  const handleScanAll = async () => {
    setScanning(true);
    try {
      await api.scanAll();
      // Delay reload to let background scan complete
      setTimeout(load, 2000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setError(msg);
    } finally {
      setScanning(false);
    }
  };

  const portalsWithDates = useMemo(
    () => portals.filter((p) => p.enabled && p.snapshot && (p.snapshot.datum_options?.length ?? 0) > 0),
    [portals]
  );

  const portalsWithErrors = useMemo(
    () => portals.filter((p) => p.enabled && p.snapshot?.error),
    [portals]
  );

  const enabledSlotNames = useMemo(() => {
    if (!config) return new Set<string>();
    const s = new Set<string>();
    if (config.reservierung.slots.morgens.enabled) s.add('morgens');
    if (config.reservierung.slots.mittags.enabled) s.add('mittags');
    if (config.reservierung.slots.abends.enabled) s.add('abends');
    return s;
  }, [config]);

  const slotLabels: Record<string, string> = { morgens: 'Morning', mittags: 'Afternoon', abends: 'Evening' };

  const matchingPortals = useMemo(() => {
    if (!config) return [];
    const wunschTage = new Set(config.reservierung.wunsch_tage);

    return portalsWithDates
      .filter((p) => p.snapshot?.datum_options?.some((d) => wunschTage.has(d.value)))
      .map((p) => {
        const deepScans = p.snapshot?.deep_scan ?? [];
        const matchingDates = (p.snapshot?.datum_options ?? []).filter((d) => wunschTage.has(d.value));

        const datesWithSlotInfo = matchingDates.map((d) => {
          const ds = deepScans.find((s) => s.datum_value === d.value);
          if (!ds) return { ...d, slotStatus: 'unknown' as const, matchingSlotNames: [] as string[] };
          const matchingSlotNames = Object.keys(ds.matching_slots).filter((s) => enabledSlotNames.has(s));
          if (matchingSlotNames.length > 0) return { ...d, slotStatus: 'match' as const, matchingSlotNames };
          return { ...d, slotStatus: 'no-match' as const, matchingSlotNames: [] as string[] };
        });

        const hasRelevantDates = datesWithSlotInfo.some((d) => d.slotStatus !== 'no-match');
        return { ...p, matchingDates: datesWithSlotInfo, hasRelevantDates };
      })
      .filter((p) => p.hasRelevantDates);
  }, [portalsWithDates, config, enabledSlotNames]);

  const isSetupComplete = config && config.user.vorname && config.reservierung.wunsch_tage.length > 0;

  return (
    <div className="space-y-6 max-w-6xl">
      {/* ── Hero Banner ── */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-wiesn-blue via-wiesn-blue-dark to-[#0a1f3d] p-7 sm:p-9 text-white animate-fade-in">
        {/* Decorative elements */}
        <div className="absolute -top-10 -right-10 w-52 h-52 rounded-full bg-wiesn-gold/8 blur-2xl" />
        <div className="absolute -bottom-16 -left-16 w-40 h-40 rounded-full bg-wiesn-blue-light/15 blur-3xl" />
        <div className="absolute top-4 right-6 text-[90px] opacity-[0.06] leading-none select-none pointer-events-none">
          🍺
        </div>

        <div className="relative">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-1.5 h-1.5 rounded-full bg-wiesn-gold pulse-dot" />
            <span className="text-[11px] uppercase tracking-widest font-medium text-wiesn-gold-light/80">
              Active — Monitoring
            </span>
          </div>

          <h1 className="text-2xl sm:text-[28px] font-bold tracking-tight mb-2 leading-snug">
            {config?.user.vorname
              ? `Hey, ${config.user.vorname}!`
              : 'Welcome to Wiesn-Agent'}
          </h1>
          <p className="text-white/60 text-sm sm:text-[15px] max-w-xl leading-relaxed">
            {matchingPortals.length > 0
              ? `There are dates on your preferred days! ${matchingPortals.length} ${matchingPortals.length === 1 ? 'tent has' : 'tents have'} matching reservations.`
              : portalsWithDates.length > 0
                ? `${portalsWithDates.length} tents currently have open dates — but none on your preferred days yet.`
                : 'The agent is monitoring the reservation portals for you. New dates will appear here automatically.'}
          </p>

          {/* Status pills */}
          <div className="mt-5 flex flex-wrap items-center gap-2">
            {summary?.last_scan && (
              <span className="inline-flex items-center gap-1.5 text-[11px] bg-white/10 backdrop-blur-sm px-3 py-1.5 rounded-full text-white/70">
                <Clock className="w-3 h-3" />
                Last scan: {timeAgo(summary.last_scan)}
              </span>
            )}
            <span className="inline-flex items-center gap-1.5 text-[11px] bg-white/10 backdrop-blur-sm px-3 py-1.5 rounded-full text-white/70">
              <Zap className="w-3 h-3" />
              Every {config?.monitoring.check_interval_minutes ?? '–'} min
            </span>
            {enabledSlotNames.size > 0 && (
              <span className="inline-flex items-center gap-1.5 text-[11px] bg-wiesn-gold/15 backdrop-blur-sm px-3 py-1.5 rounded-full text-wiesn-gold-light/90">
                🕐 {[...enabledSlotNames].map((s) => slotLabels[s] ?? s).join(', ')}
              </span>
            )}
          </div>

          <button
            onClick={handleScanAll}
            disabled={scanning}
            className="mt-6 inline-flex items-center gap-2 px-5 py-2.5 bg-wiesn-gold text-wiesn-brown-dark rounded-xl font-semibold text-sm hover:bg-wiesn-gold-light transition-all duration-200 disabled:opacity-50 shadow-lg shadow-wiesn-gold/20 hover:shadow-wiesn-gold/30 hover:-translate-y-px active:translate-y-0"
          >
            <RefreshCw className={`w-4 h-4 ${scanning ? 'animate-spin' : ''}`} />
            {scanning ? 'Scanning all portals…' : 'Scan now'}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-3 bg-wiesn-error/5 border border-wiesn-error/20 text-wiesn-error rounded-xl px-4 py-3 text-sm animate-fade-in">
          <XCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* ── Onboarding Steps ── */}
      {!isSetupComplete && (
        <div className="bg-white border border-wiesn-gold/20 rounded-2xl overflow-hidden animate-fade-in animate-fade-in-delay-1">
          <div className="bg-wiesn-gold/5 px-6 py-4 border-b border-wiesn-gold/15">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-wiesn-gold/15 flex items-center justify-center flex-shrink-0">
                <Zap className="w-5 h-5 text-wiesn-gold" />
              </div>
              <div>
                <h3 className="font-semibold text-wiesn-brown-dark text-[15px]">Getting Started</h3>
                <p className="text-[12px] text-wiesn-text-muted mt-0.5">Complete these steps to get the agent working for you</p>
              </div>
            </div>
          </div>
          <div className="divide-y divide-wiesn-border-light">
            {[
              {
                done: Boolean(config?.user.vorname && config?.user.nachname),
                label: 'Add your name & contact info',
                detail: 'Required for the reservation form',
              },
              {
                done: Boolean(config?.user.email),
                label: 'Set your email address',
                detail: 'For reservation confirmation',
              },
              {
                done: (config?.reservierung.wunsch_tage.length ?? 0) > 0,
                label: 'Choose your preferred dates',
                detail: 'The scanner will match these against available slots',
              },
              {
                done: enabledSlotNames.size > 0,
                label: 'Enable at least one time slot',
                detail: 'Morning, Afternoon, or Evening',
              },
            ].map((step, i) => (
              <div
                key={i}
                className={`flex items-center gap-3 px-6 py-3.5 ${step.done ? 'opacity-60' : ''}`}
              >
                {step.done ? (
                  <CheckCircle className="w-5 h-5 text-wiesn-success flex-shrink-0" />
                ) : (
                  <div className="w-5 h-5 rounded-full border-2 border-wiesn-gold/40 flex-shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <p className={`text-sm font-medium ${step.done ? 'text-wiesn-text-muted line-through' : 'text-wiesn-brown-dark'}`}>
                    {step.label}
                  </p>
                  <p className="text-[11px] text-wiesn-text-muted">{step.detail}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="px-6 py-3 bg-wiesn-cream/50 border-t border-wiesn-border-light">
            <button
              onClick={() => navigate('/settings')}
              className="inline-flex items-center gap-2 px-4 py-2 bg-wiesn-gold/15 text-wiesn-gold-dark rounded-lg text-sm font-medium hover:bg-wiesn-gold/25 transition-colors"
            >
              Open settings
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* ── Matches ── */}
      {matchingPortals.length > 0 && (
        <section className="animate-fade-in animate-fade-in-delay-1">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="w-2 h-2 rounded-full bg-wiesn-success pulse-dot" />
            <h2 className="text-[15px] font-semibold text-wiesn-brown-dark tracking-tight">
              Matches — Dates on your preferred days
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {matchingPortals.map((p) => (
              <a
                key={p.name}
                href={p.url}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-white border border-wiesn-success/20 rounded-2xl p-5 hover:border-wiesn-success/40 hover:shadow-md hover:shadow-wiesn-success/5 transition-all duration-200 group"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-wiesn-success/10 flex items-center justify-center">
                      <TentTree className="w-4 h-4 text-wiesn-success" />
                    </div>
                    <h3 className="font-semibold text-wiesn-brown-dark text-sm group-hover:text-wiesn-blue transition-colors">
                      {p.name}
                    </h3>
                  </div>
                  <ExternalLink className="w-3.5 h-3.5 text-wiesn-text-muted group-hover:text-wiesn-blue transition-colors mt-1" />
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {p.matchingDates.map((d) => (
                    <span
                      key={d.value}
                      className={`text-[11px] px-2.5 py-1 rounded-lg font-medium ${
                        d.slotStatus === 'match'
                          ? 'bg-wiesn-success/10 text-wiesn-success'
                          : d.slotStatus === 'no-match'
                            ? 'bg-gray-50 text-gray-400 line-through'
                            : 'bg-wiesn-gold/10 text-wiesn-brown'
                      }`}
                      title={
                        d.slotStatus === 'match'
                          ? `${d.matchingSlotNames.map((s) => slotLabels[s] ?? s).join(', ')} available`
                          : d.slotStatus === 'no-match'
                            ? 'No matching time slots'
                            : 'Time slots not yet checked'
                      }
                    >
                      {formatDate(d.value)}
                      {d.slotStatus === 'match' && ' ✓'}
                      {d.slotStatus === 'unknown' && ' ?'}
                    </span>
                  ))}
                </div>
                {p.matchingDates.some((d) => d.slotStatus === 'unknown') && (
                  <p className="text-[11px] text-wiesn-text-muted mt-2.5">
                    ⏳ Time slots will be checked in the next scan
                  </p>
                )}
              </a>
            ))}
          </div>
        </section>
      )}

      {/* ── Stat Cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 animate-fade-in animate-fade-in-delay-2">
        <Link
          to="/portals"
          className="bg-white border border-wiesn-border-light rounded-2xl p-5 text-left hover:border-wiesn-gold/40 hover:shadow-md hover:shadow-wiesn-gold/5 transition-all duration-200 group"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-10 rounded-xl bg-wiesn-success/8 flex items-center justify-center">
              <Calendar className="w-5 h-5 text-wiesn-success" />
            </div>
            <ArrowRight className="w-4 h-4 text-wiesn-text-muted group-hover:text-wiesn-gold group-hover:translate-x-0.5 transition-all" />
          </div>
          <p className="text-[28px] font-bold text-wiesn-brown-dark tracking-tight mb-0.5">{portalsWithDates.length}</p>
          <p className="text-sm text-wiesn-text-light">
            {portalsWithDates.length === 1 ? 'Tent' : 'Tents'} with dates
          </p>
          {portalsWithDates.length > 0 && (
            <p className="text-[11px] text-wiesn-success mt-2 font-medium">
              {summary?.total_dates_available ?? 0} available dates
            </p>
          )}
        </Link>

        <Link
          to="/portals"
          className="bg-white border border-wiesn-border-light rounded-2xl p-5 text-left hover:border-wiesn-gold/40 hover:shadow-md hover:shadow-wiesn-gold/5 transition-all duration-200 group"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-10 rounded-xl bg-wiesn-blue/8 flex items-center justify-center">
              <Beer className="w-5 h-5 text-wiesn-blue" />
            </div>
            <ArrowRight className="w-4 h-4 text-wiesn-text-muted group-hover:text-wiesn-gold group-hover:translate-x-0.5 transition-all" />
          </div>
          <p className="text-[28px] font-bold text-wiesn-brown-dark tracking-tight mb-0.5">
            {summary?.enabled_portals ?? 0}
            <span className="text-base text-wiesn-text-muted font-normal ml-0.5">/{summary?.total_portals ?? 0}</span>
          </p>
          <p className="text-sm text-wiesn-text-light">Portals monitored</p>
        </Link>

        <Link
          to="/portals"
          className="bg-white border border-wiesn-border-light rounded-2xl p-5 text-left hover:border-wiesn-gold/40 hover:shadow-md hover:shadow-wiesn-gold/5 transition-all duration-200 group"
        >
          <div className="flex items-center justify-between mb-4">
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
              portalsWithErrors.length > 0 ? 'bg-wiesn-error/8' : 'bg-wiesn-success/8'
            }`}>
              {portalsWithErrors.length > 0
                ? <XCircle className="w-5 h-5 text-wiesn-error" />
                : <CheckCircle className="w-5 h-5 text-wiesn-success" />}
            </div>
            <ArrowRight className="w-4 h-4 text-wiesn-text-muted group-hover:text-wiesn-gold group-hover:translate-x-0.5 transition-all" />
          </div>
          <p className="text-[28px] font-bold text-wiesn-brown-dark tracking-tight mb-0.5">{portalsWithErrors.length}</p>
          <p className="text-sm text-wiesn-text-light">
            {portalsWithErrors.length === 0 ? 'No errors — all good' : 'Portals with errors'}
          </p>
        </Link>
      </div>

      {/* ── Tents with dates ── */}
      {portalsWithDates.length > 0 && (
        <section className="bg-white border border-wiesn-border-light rounded-2xl overflow-hidden animate-fade-in animate-fade-in-delay-3">
          <div className="flex items-center justify-between px-6 py-4 border-b border-wiesn-border-light">
            <h2 className="text-[15px] font-semibold text-wiesn-brown-dark tracking-tight">
              Tents with open dates
            </h2>
            <button
              onClick={() => navigate('/portals')}
              className="text-[13px] text-wiesn-blue hover:text-wiesn-blue-light font-medium inline-flex items-center gap-1 transition-colors"
            >
              Show all <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="divide-y divide-wiesn-border-light">
            {portalsWithDates.slice(0, 6).map((p) => {
              const dates = p.snapshot!.datum_options;
              return (
                <a
                  key={p.name}
                  href={p.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-between py-3.5 px-6 hover:bg-wiesn-cream/50 transition-colors group"
                >
                  <div className="min-w-0 flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-wiesn-gold/8 flex items-center justify-center flex-shrink-0">
                      <TentTree className="w-4 h-4 text-wiesn-gold-dark" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-wiesn-brown-dark group-hover:text-wiesn-blue transition-colors truncate">
                        {p.name}
                      </p>
                      <p className="text-[11px] text-wiesn-text-muted">
                        {p.snapshot!.portal_type} · {timeAgo(p.snapshot!.timestamp)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0 ml-3">
                    <span className="text-sm font-semibold text-wiesn-success tabular-nums">
                      {dates.length}
                    </span>
                    <span className="text-[11px] text-wiesn-text-muted hidden sm:inline">
                      {dates.length === 1 ? 'date' : 'dates'}
                    </span>
                    <ExternalLink className="w-3.5 h-3.5 text-wiesn-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                </a>
              );
            })}
          </div>
        </section>
      )}

      {/* ── Empty state ── */}
      {!summary?.last_scan && (
        <div className="bg-white border border-wiesn-border-light rounded-2xl p-10 text-center animate-fade-in animate-fade-in-delay-2">
          <div className="w-14 h-14 rounded-2xl bg-wiesn-blue/8 flex items-center justify-center mx-auto mb-4">
            <Beer className="w-7 h-7 text-wiesn-blue" />
          </div>
          <h3 className="font-semibold text-wiesn-brown-dark text-[15px] mb-2">No scans yet</h3>
          <p className="text-sm text-wiesn-text-light max-w-md mx-auto leading-relaxed">
            Click "Scan now" to check the reservation portals.
            After that, the scanner will run automatically.
          </p>
        </div>
      )}
    </div>
  );
}
