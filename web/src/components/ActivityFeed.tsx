import { useEffect, useRef, useState, useCallback, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
import { Bot, Send, X, MessageSquare, Sparkles, ArrowRight } from 'lucide-react';
import type { ChatMessage } from '../api';
import { api, createAuthSSE } from '../api';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(iso));
}

/** Lightweight inline Markdown renderer: **bold**, [links](url), `code`, - bullets */
function renderMarkdown(text: string): ReactNode[] {
  const lines = text.split('\n');
  return lines.map((line, li) => {
    const trimmed = line.trim();

    // Bullet list item
    if (trimmed.startsWith('- ') || trimmed.startsWith('• ')) {
      return (
        <div key={li} className="flex gap-2 pl-1">
          <span className="text-wiesn-gold/50 select-none">•</span>
          <span className="flex-1">{renderInline(trimmed.slice(2))}</span>
        </div>
      );
    }

    // Empty line → spacer
    if (!trimmed) return <div key={li} className="h-1.5" />;

    return <p key={li}>{renderInline(line)}</p>;
  });
}

function renderInline(text: string): ReactNode[] {
  // Match: **bold**, [text](url), `code`
  const regex = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\)|`[^`]+`)/g;
  const parts = text.split(regex);

  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="font-semibold text-white">{part.slice(2, -2)}</strong>;
    }
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      const href = linkMatch[2];
      // Block dangerous URL schemes (XSS prevention)
      if (!/^https?:\/\//i.test(href) && !/^mailto:/i.test(href)) {
        return <span key={i}>{linkMatch[1]}</span>;
      }
      return (
        <a key={i} href={href} target="_blank" rel="noopener noreferrer"
          className="text-wiesn-gold hover:text-wiesn-gold-light underline underline-offset-2 decoration-wiesn-gold/30">
          {linkMatch[1]}
        </a>
      );
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={i} className="bg-white/10 text-wiesn-gold-light px-1.5 py-0.5 rounded text-[12px] font-mono">{part.slice(1, -1)}</code>;
    }
    return <span key={i}>{part}</span>;
  });
}


// ─── Typing Indicator ────────────────────────────────────────────────────────

function TypingIndicator({ steps }: { steps: string[] }) {
  return (
    <div className="flex justify-start animate-fade-in">
      <div className="flex items-end gap-2">
        <div className="w-7 h-7 rounded-full bg-wiesn-gold/15 flex items-center justify-center flex-shrink-0 mb-0.5">
          <Bot className="w-3.5 h-3.5 text-wiesn-gold" aria-hidden="true" />
        </div>
        <div className="bg-white/6 rounded-2xl rounded-bl-md px-4 py-3 space-y-1">
          {steps.map((step, i) => (
            <p key={i} className={`text-[12px] leading-snug ${i === steps.length - 1 ? 'text-white/70' : 'text-white/35'}`}>
              {step}
            </p>
          ))}
          <div className="flex items-center gap-1.5 pt-0.5">
            {steps.length === 0 && <span className="text-white/30 text-[12px] mr-1">Thinking</span>}
            <span className="w-1.5 h-1.5 rounded-full bg-wiesn-gold/50 animate-bounce motion-reduce:animate-none [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-wiesn-gold/50 animate-bounce motion-reduce:animate-none [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-wiesn-gold/50 animate-bounce motion-reduce:animate-none [animation-delay:300ms]" />
          </div>
        </div>
      </div>
    </div>
  );
}


// ─── Suggestion Chips ────────────────────────────────────────────────────────

const SUGGESTIONS = [
  { label: 'Welche Zelte haben freie Termine?', icon: '🍺' },
  { label: 'Check das Hacker-Festzelt', icon: '🔍' },
  { label: 'Gibt es Abend-Slots am 25.9.?', icon: '🌙' },
  { label: 'Zeig mir den Status', icon: '📊' },
];

function SuggestionChips({ onSelect }: { onSelect: (text: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2 mt-3">
      {SUGGESTIONS.map((s) => (
        <button
          key={s.label}
          onClick={() => onSelect(s.label)}
          className="inline-flex items-center gap-1.5 text-[12px] bg-white/6 hover:bg-white/12 text-white/60 hover:text-white/90 rounded-xl px-3 py-2 transition-all duration-200 border border-white/6 hover:border-white/15"
        >
          <span>{s.icon}</span>
          <span>{s.label}</span>
        </button>
      ))}
    </div>
  );
}


// ─── Welcome Screen ──────────────────────────────────────────────────────────

function WelcomeScreen({ onSelect }: { onSelect: (text: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full px-6 animate-fade-in">
      <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-wiesn-gold/20 to-wiesn-gold/5 flex items-center justify-center mb-4">
        <Sparkles className="w-7 h-7 text-wiesn-gold" aria-hidden="true" />
      </div>
      <h3 className="text-white font-semibold text-[15px] mb-1">Wiesn-Agent</h3>
      <p className="text-white/30 text-[12px] text-center leading-relaxed mb-1">
        AI-powered assistant for Oktoberfest reservations
      </p>
      <p className="text-white/20 text-[11px] text-center leading-relaxed mb-6">
        I can check portals, find available dates, fill forms, and more.
      </p>
      <div className="w-full space-y-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.label}
            onClick={() => onSelect(s.label)}
            className="w-full flex items-center gap-3 text-left text-[13px] bg-white/5 hover:bg-white/10 text-white/60 hover:text-white/80 rounded-xl px-4 py-3 transition-all duration-200 border border-white/5 hover:border-white/12 group"
          >
            <span className="text-base">{s.icon}</span>
            <span className="flex-1">{s.label}</span>
            <ArrowRight className="w-3.5 h-3.5 text-white/15 group-hover:text-white/40 transition-colors" aria-hidden="true" />
          </button>
        ))}
      </div>
    </div>
  );
}


// ─── Main Component ──────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  onClose: () => void;
}

const CHAT_STORAGE_KEY = 'wiesn-chat-messages';

function cacheMessages(msgs: ChatMessage[]) {
  try { sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(msgs.slice(-200))); } catch { /* quota */ }
}

function loadCachedMessages(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(CHAT_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

export default function ActivityFeed({ open, onClose }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>(loadCachedMessages);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [thinkingSteps, setThinkingSteps] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ── Persist to sessionStorage on change ──────────
  useEffect(() => { cacheMessages(messages); }, [messages]);

  // ── Load history + SSE ───────────────────────────
  useEffect(() => {
    if (!open) return;

    // Merge server history into local state (don't replace — FE-4 fix)
    api.getChat().then((serverMsgs) => {
      const filtered = serverMsgs.filter((m: ChatMessage) => m.role !== 'thinking');
      if (filtered.length > 0) {
        setMessages((prev) => {
          if (prev.length === 0) return filtered;
          // Merge: keep local optimistic messages, add server messages we don't have
          const existingIds = new Set(prev.map((m) => m.event_id).filter(Boolean));
          const newFromServer = filtered.filter(
            (m: ChatMessage) => m.event_id && !existingIds.has(m.event_id),
          );
          return newFromServer.length > 0 ? [...prev, ...newFromServer] : prev;
        });
      }
    }).catch(() => {});

    let retryTimeout: ReturnType<typeof setTimeout>;
    let retryCount = 0;
    let sseHandle: { close: () => void } | null = null;
    let lastEventId = 0;

    function connectSSE() {
      sseHandle = createAuthSSE(
        '/chat/stream',
        (data: unknown) => {
          const msg = data as Record<string, unknown>;
          if (msg.type === 'connected') {
            setConnected(true);
            retryCount = 0;
            return;
          }

          // Track event_id for dedup (FE-3 fix)
          const eid = (msg.event_id as number) ?? 0;
          if (eid > 0 && eid <= lastEventId) return;
          if (eid > 0) lastEventId = eid;

          // Thinking progress
          if (msg.role === 'thinking') {
            const text = (msg.message as string) || '';
            if (text) {
              setThinkingSteps((prev) => {
                if (prev[prev.length - 1] === text) return prev;
                return [...prev.slice(-9), text];
              });
            }
            return;
          }

          // Skip user messages from SSE — already added optimistically
          if (msg.role === 'user') return;

          // Clear thinking steps when agent replies
          if (msg.role === 'agent') setThinkingSteps([]);

          setMessages((prev) => {
            // Deduplicate by event_id
            if (eid > 0 && prev.some((m) => m.event_id === eid)) return prev;
            return [...prev.slice(-299), msg as unknown as ChatMessage];
          });
        },
        () => {
          setConnected(false);
          const delay = Math.min(1000 * 2 ** retryCount, 30_000);
          retryCount++;
          retryTimeout = setTimeout(connectSSE, delay);
        },
      );
    }

    connectSSE();

    return () => {
      clearTimeout(retryTimeout);
      sseHandle?.close();
      setConnected(false);
    };
  }, [open]);

  // ── Auto-scroll ──────────────────────────────────
  useEffect(() => {
    if (bottomRef.current && containerRef.current) {
      const c = containerRef.current;
      const nearBottom = c.scrollHeight - c.scrollTop - c.clientHeight < 150;
      if (nearBottom) bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, sending, thinkingSteps]);

  // ── Focus + Escape ───────────────────────────────
  useEffect(() => {
    if (open) setTimeout(() => textareaRef.current?.focus(), 200);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // ── Auto-resize textarea ─────────────────────────
  const adjustTextarea = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
  }, []);

  useEffect(() => { adjustTextarea(); }, [input, adjustTextarea]);

  // ── Send message ─────────────────────────────────
  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || sending) return;

      setInput('');
      setSending(true);
      setThinkingSteps([]);

      const userMsg: ChatMessage = { timestamp: new Date().toISOString(), role: 'user', message: trimmed };
      setMessages((prev) => [...prev, userMsg]);

      try {
        const { reply } = await api.sendChat(trimmed);
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.timestamp === reply.timestamp && last.message === reply.message) return prev;
          return [...prev, reply];
        });
      } catch {
        setMessages((prev) => [
          ...prev,
          { timestamp: new Date().toISOString(), role: 'agent', message: 'Something went wrong — please try again.' },
        ]);
      } finally {
        setSending(false);
        textareaRef.current?.focus();
      }
    },
    [sending],
  );

  const handleSubmit = useCallback(
    (e?: FormEvent) => {
      e?.preventDefault();
      sendMessage(input);
    },
    [input, sendMessage],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  if (!open) return null;

  const isEmpty = messages.length === 0;

  return (
    <div
      role="dialog"
      aria-label="Wiesn-Agent Chat"
      aria-modal="true"
      id="chat-panel"
      className="fixed right-0 top-0 bottom-0 w-full sm:w-[420px] bg-[#0f1318] border-l border-white/8 z-50 flex flex-col shadow-2xl overscroll-contain"
    >
      {/* ── Header ─────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-3.5 border-b border-white/8 bg-white/[0.02]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-wiesn-gold/15 flex items-center justify-center">
            <MessageSquare className="w-4 h-4 text-wiesn-gold" aria-hidden="true" />
          </div>
          <div>
            <span className="text-white font-semibold text-sm block leading-tight">Wiesn-Agent</span>
            <span className="text-white/30 text-[10px] flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full inline-block ${connected ? 'bg-emerald-400' : 'bg-white/20'}`} />
              {connected ? 'Connected' : 'Connecting…'}
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 hover:bg-white/8 rounded-lg transition-colors text-white/40 hover:text-white"
          aria-label="Close chat"
        >
          <X className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>

      {/* ── Messages ───────────────────────────── */}
      <div ref={containerRef} className="flex-1 overflow-y-auto px-3 py-4 space-y-3" aria-live="polite" aria-relevant="additions">
        {isEmpty && !sending && <WelcomeScreen onSelect={sendMessage} />}

        {messages.map((msg, i) => {
          // ── User message
          if (msg.role === 'user') {
            return (
              <div key={`${msg.timestamp}-${i}`} className="flex justify-end animate-fade-in">
                <div className="max-w-[82%]">
                  <div className="bg-wiesn-blue rounded-2xl rounded-br-md px-3.5 py-2.5">
                    <p className="text-white text-[13px] leading-relaxed whitespace-pre-wrap">{msg.message}</p>
                  </div>
                  <p className="text-white/15 text-[10px] mt-1 text-right pr-1">{formatTime(msg.timestamp)}</p>
                </div>
              </div>
            );
          }

          // ── Agent message
          if (msg.role === 'agent') {
            return (
              <div key={`${msg.timestamp}-${i}`} className="flex justify-start animate-fade-in">
                <div className="flex items-start gap-2 max-w-[88%]">
                  <div className="w-7 h-7 rounded-full bg-wiesn-gold/15 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Bot className="w-3.5 h-3.5 text-wiesn-gold" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="bg-white/6 rounded-2xl rounded-tl-md px-3.5 py-2.5">
                      <div className="text-white/80 text-[13px] leading-relaxed space-y-0.5">
                        {renderMarkdown(msg.message)}
                      </div>
                    </div>
                    <p className="text-white/15 text-[10px] mt-1 pl-1">{formatTime(msg.timestamp)}</p>
                  </div>
                </div>
              </div>
            );
          }

          // ── System message (should be rare now)
          return (
            <div key={`${msg.timestamp}-${i}`} className="text-center animate-fade-in">
              <span className="text-white/20 text-[11px] bg-white/5 rounded-full px-3 py-1 inline-block">
                {msg.message}
              </span>
            </div>
          );
        })}

        {/* ── Typing indicator while waiting ── */}
        {sending && <TypingIndicator steps={thinkingSteps} />}

        {/* ── Suggestion chips after first reply ── */}
        {!isEmpty && !sending && messages[messages.length - 1]?.role === 'agent' && messages.length <= 4 && (
          <SuggestionChips onSelect={sendMessage} />
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input ──────────────────────────────── */}
      <div className="px-3 py-3 border-t border-white/8 bg-white/[0.02]">
        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              name="chat-message"
              aria-label="Chat message"
              placeholder="Ask me anything about Oktoberfest reservations…"
              autoComplete="off"
              spellCheck
              disabled={sending}
              rows={1}
              className="w-full bg-white/6 text-white text-[13px] placeholder:text-white/20 rounded-xl px-4 py-2.5 outline-none focus-visible:ring-1 focus-visible:ring-wiesn-gold/30 focus-visible:bg-white/8 disabled:opacity-40 transition-colors resize-none leading-relaxed"
              style={{ maxHeight: '120px' }}
            />
          </div>
          <button
            type="submit"
            disabled={!input.trim() || sending}
            aria-label="Send message"
            className="w-9 h-9 rounded-xl bg-wiesn-gold flex items-center justify-center text-wiesn-brown-dark hover:bg-wiesn-gold-light disabled:opacity-20 disabled:hover:bg-wiesn-gold transition-colors duration-200 flex-shrink-0 mb-0.5"
          >
            <Send className="w-4 h-4" aria-hidden="true" />
          </button>
        </form>
        <p className="text-white/10 text-[10px] mt-2 text-center">
          AI assistant — responses may not always be accurate
        </p>
      </div>
    </div>
  );
}
