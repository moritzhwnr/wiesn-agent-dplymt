import { useEffect, useState, useCallback } from 'react';
import { X, ExternalLink, Bell } from 'lucide-react';
import { createAuthSSE } from '../api';

interface SlotAlert {
  alert_id: number;
  timestamp: string;
  portal: string;
  date: string;
  times: string;
  url: string;
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

export default function SlotToast() {
  const [alerts, setAlerts] = useState<SlotAlert[]>([]);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const [browserNotifGranted, setBrowserNotifGranted] = useState(
    typeof Notification !== 'undefined' && Notification.permission === 'granted'
  );

  const requestBrowserNotifs = useCallback(() => {
    if (typeof Notification === 'undefined') return;
    if (Notification.permission === 'default') {
      Notification.requestPermission().then((p) => {
        setBrowserNotifGranted(p === 'granted');
      });
    }
  }, []);

  // Request browser notification permission on first render
  useEffect(() => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      // Delay to avoid blocking the page load
      const t = setTimeout(requestBrowserNotifs, 5000);
      return () => clearTimeout(t);
    }
  }, [requestBrowserNotifs]);

  // Connect to SSE alert stream
  useEffect(() => {
    let sseHandle: { close: () => void } | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      // Close previous handle to prevent duplicate subscriptions
      if (sseHandle) {
        sseHandle.close();
        sseHandle = null;
      }

      // Hydrate existing alerts on (re)connect
      fetch('/api/alerts')
        .then((r) => r.json())
        .then((data) => {
          if (data.alerts?.length) {
            setAlerts((prev) => {
              const ids = new Set(prev.map((a) => a.alert_id));
              const newAlerts = (data.alerts as SlotAlert[]).filter((a) => !ids.has(a.alert_id));
              return [...prev, ...newAlerts].slice(-10);
            });
          }
        })
        .catch(() => { /* hydration is best-effort */ });

      sseHandle = createAuthSSE(
        '/alerts/stream',
        (raw) => {
          const data = raw as Record<string, unknown>;
          if (data.type === 'connected') return;
          if (data.type === 'slot_alert') {
            const alert = data as unknown as SlotAlert;
            setAlerts((prev) => {
              if (prev.some((a) => a.alert_id === alert.alert_id)) return prev;
              return [...prev, alert].slice(-10);
            });

            // Browser notification
            if (browserNotifGranted && typeof Notification !== 'undefined') {
              try {
                new Notification(`🍺🌙 ${alert.portal}`, {
                  body: `📅 ${alert.date}\n🌙 ${alert.times}`,
                  icon: '/favicon.svg',
                  tag: `slot-${alert.alert_id}`,
                });
              } catch {
                // Notifications not supported in this context
              }
            }
          }
        },
        () => {
          // On disconnect, retry after 5s (prevent duplicate via timer)
          if (reconnectTimer) clearTimeout(reconnectTimer);
          reconnectTimer = setTimeout(connect, 5000);
        },
      );
    }

    connect();
    return () => {
      sseHandle?.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [browserNotifGranted]);

  // Auto-dismiss toasts after 30 seconds
  useEffect(() => {
    const timers = alerts
      .filter((a) => !dismissed.has(a.alert_id))
      .map((a) => {
        const age = Date.now() - new Date(a.timestamp).getTime();
        const remaining = Math.max(30000 - age, 0);
        return setTimeout(() => {
          setDismissed((prev) => new Set([...prev, a.alert_id]));
        }, remaining);
      });
    return () => timers.forEach(clearTimeout);
  }, [alerts, dismissed]);

  const visible = alerts.filter((a) => !dismissed.has(a.alert_id));
  if (visible.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 max-w-sm w-full pointer-events-none">
      {visible.map((alert) => (
        <div
          key={alert.alert_id}
          className="pointer-events-auto bg-white border border-wiesn-gold/30 rounded-2xl shadow-2xl shadow-wiesn-gold/10 p-4 animate-fade-in motion-reduce:animate-none"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-wiesn-gold/15 flex items-center justify-center flex-shrink-0">
                <span className="text-lg" role="img" aria-label="Beer">🍺</span>
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-wiesn-brown-dark truncate">
                  🌙 {alert.portal}
                </p>
                <p className="text-xs text-wiesn-text-light">
                  📅 {alert.date} · {alert.times}
                </p>
              </div>
            </div>
            <button
              onClick={() => setDismissed((prev) => new Set([...prev, alert.alert_id]))}
              className="text-wiesn-text-muted hover:text-wiesn-text p-1 rounded-lg hover:bg-wiesn-cream transition-colors flex-shrink-0"
              aria-label="Dismiss notification"
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>
          <div className="flex items-center justify-between mt-3 pt-2.5 border-t border-wiesn-border-light">
            <span className="text-[11px] text-wiesn-text-muted">{timeAgo(alert.timestamp)}</span>
            {alert.url && (
              <a
                href={alert.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs font-medium text-wiesn-blue hover:text-wiesn-blue-light transition-colors"
              >
                Book now
                <ExternalLink className="w-3 h-3" aria-hidden="true" />
              </a>
            )}
          </div>
        </div>
      ))}

      {/* Browser notification permission prompt */}
      {typeof Notification !== 'undefined' && Notification.permission === 'default' && (
        <div className="pointer-events-auto bg-wiesn-cream border border-wiesn-border rounded-2xl p-3 animate-fade-in">
          <button
            onClick={requestBrowserNotifs}
            className="flex items-center gap-2 text-xs text-wiesn-text-light hover:text-wiesn-text transition-colors w-full"
          >
            <Bell className="w-4 h-4 text-wiesn-gold" aria-hidden="true" />
            <span>Enable browser notifications for slot alerts</span>
          </button>
        </div>
      )}
    </div>
  );
}
