// ─── Types ───────────────────────────────────────────────────────────────────

export interface ActivityEvent {
  timestamp: string;
  level: string;
  message: string;
  portal?: string;
  event?: string;
}

export interface ChatMessage {
  event_id?: number;
  timestamp: string;
  role: 'user' | 'agent' | 'system' | 'thinking';
  message: string;
  level?: string;
  portal?: string;
  event?: string;
}

export interface DatumOption {
  value: string;
  text: string;
}

export interface DeepScanResult {
  datum_value: string;
  datum_text: string;
  uhrzeiten: { value: string; text: string }[];
  matching_slots: Record<string, { value: string; text: string }[]>;
}

export interface PortalSnapshot {
  portal_name: string;
  portal_url: string;
  timestamp: string;
  datum_options: DatumOption[];
  portal_type: string;
  error?: string;
  deep_scan?: DeepScanResult[];
}

export interface Portal {
  name: string;
  url: string;
  enabled: boolean;
  snapshot: PortalSnapshot | null;
}

export interface DailyStat {
  date: string;
  scans: number;
  total_dates: number;
  new_dates: number;
  evening_slots: number;
  errors: number;
  portals_scanned: number;
}

export interface PortalStat {
  portal: string;
  url: string;
  type: string;
  total_scans: number;
  total_dates: number;
  total_new: number;
  total_evening: number;
  last_scan: string;
  errors: number;
}

export interface Summary {
  total_portals: number;
  enabled_portals: number;
  portals_with_dates: number;
  total_dates_available: number;
  scan_errors: number;
  history_records: number;
  last_scan: string;
}

export interface SlotConfig {
  enabled: boolean;
  von: string;
  bis: string;
  prioritaet: number;
}

export interface Config {
  user: {
    vorname: string;
    nachname: string;
    email: string;
    telefon: string;
    personen: number;
    notizen: string;
  };
  reservierung: {
    wunsch_tage: string[];
    slots: {
      morgens: SlotConfig;
      mittags: SlotConfig;
      abends: SlotConfig;
    };
  };
  monitoring: {
    check_interval_minutes: number;
    screenshot_on_change: boolean;
  };
  notifications: {
    desktop: boolean;
    apprise_urls: string[];
    botbell_token: string;
    use_emojis: boolean;
    nur_an_tagen: string[];
    stille_zeit: { von: string; bis: string };
  };
}

// ─── API Client ──────────────────────────────────────────────────────────────

const BASE = '/api';

/**
 * Read auth token from localStorage (set via Settings or env).
 * When empty, no Authorization header is sent (open API mode).
 */
function getAuthToken(): string {
  return localStorage.getItem('wiesn_api_token') ?? '';
}

export function setAuthToken(token: string): void {
  if (token) {
    localStorage.setItem('wiesn_api_token', token);
  } else {
    localStorage.removeItem('wiesn_api_token');
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { ...headers, ...(options?.headers as Record<string, string> ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => 'Unknown error');
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

/**
 * Create an authenticated SSE connection.
 * Falls back to native EventSource when no token is set.
 * When a token is configured, uses fetch + ReadableStream since
 * EventSource cannot send custom headers.
 */
export function createAuthSSE(
  path: string,
  onMessage: (data: unknown) => void,
  onError?: () => void,
): { close: () => void } {
  const token = getAuthToken();
  const url = `${BASE}${path}`;

  if (!token) {
    // No auth needed — use native EventSource
    const es = new EventSource(url);
    es.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data)); } catch { /* ignore */ }
    };
    es.onerror = () => { onError?.(); };
    return { close: () => es.close() };
  }

  // Auth mode: use fetch with streaming
  const controller = new AbortController();
  let closed = false;

  (async () => {
    try {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (!res.ok || !res.body) { onError?.(); return; }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (!closed) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try { onMessage(JSON.parse(line.slice(6))); } catch { /* ignore */ }
          }
        }
      }
    } catch {
      if (!closed) onError?.();
    }
  })();

  return { close: () => { closed = true; controller.abort(); } };
}

export interface ScanResult {
  portal: string;
  dates_found: number;
  new_dates: number;
  portal_type: string;
  error?: string;
  summary: string;
}

export interface ScanResponse {
  results: ScanResult[];
  scanned: number;
}

export const api = {
  // Portals
  getPortals: () =>
    request<{ portals: Portal[] }>('/portals').then((r) => r.portals),

  getSnapshots: () =>
    request<Record<string, PortalSnapshot>>('/snapshots'),

  togglePortal: (name: string, enabled: boolean) =>
    request<{ enabled: boolean }>(`/portals/${encodeURIComponent(name)}/toggle`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),

  // Scanning
  scan: (portalName: string) =>
    request<ScanResponse>(`/scan/${encodeURIComponent(portalName)}`, { method: 'POST' }),

  scanAll: () =>
    request<ScanResponse>('/scan/all', { method: 'POST' }),

  // Stats
  getDailyStats: () =>
    request<{ stats: DailyStat[] }>('/stats/daily').then((r) => r.stats),

  getPortalStats: () =>
    request<{ stats: PortalStat[] }>('/stats/portals').then((r) => r.stats),

  getSummary: () =>
    request<Summary>('/stats/summary'),

  // Config
  getConfig: () =>
    request<Config>('/config'),

  updateConfig: (config: Partial<Config>) =>
    request<Config>('/config', {
      method: 'PUT',
      body: JSON.stringify(config),
    }),

  // Activity
  getActivity: () =>
    request<{ events: ActivityEvent[] }>('/activity').then((r) => r.events),

  // Chat
  getChat: () =>
    request<{ messages: ChatMessage[] }>('/chat').then((r) => r.messages),

  sendChat: (message: string) =>
    request<{ user: ChatMessage; reply: ChatMessage }>('/chat', {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),
};
