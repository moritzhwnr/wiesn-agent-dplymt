import { api } from '../api';
import type { Portal } from '../api';
import StatusBadge from './StatusBadge';
import { Clock, Calendar, AlertTriangle } from 'lucide-react';

interface PortalCardProps {
  portal: Portal;
  onToggle: (name: string, enabled: boolean) => void;
}

export default function PortalCard({ portal, onToggle }: PortalCardProps) {
  const { name, enabled, snapshot } = portal;
  const datesCount = snapshot?.datum_options?.length ?? 0;
  const hasError = !!snapshot?.error;
  const hasDate = datesCount > 0;

  let accentClass = 'border-wiesn-border-light';
  if (hasError) accentClass = 'border-wiesn-error/30';
  else if (hasDate) accentClass = 'border-wiesn-success/30';
  else if (snapshot) accentClass = 'border-wiesn-warning/20';

  let statusDot = 'bg-gray-300';
  if (hasError) statusDot = 'bg-wiesn-error';
  else if (hasDate) statusDot = 'bg-wiesn-success pulse-dot';
  else if (snapshot) statusDot = 'bg-wiesn-warning';

  const formatTime = (ts: string) => {
    try {
      return new Intl.DateTimeFormat(undefined, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(ts));
    } catch {
      return ts;
    }
  };

  const handleToggle = async () => {
    try {
      await api.togglePortal(name, !enabled);
      onToggle(name, !enabled);
    } catch (e) {
      console.error('Toggle failed:', e);
    }
  };

  return (
    <div
      className={`bg-white border ${accentClass} rounded-2xl p-5 transition-shadow duration-200 hover:shadow-md hover:shadow-black/5 ${
        !enabled ? 'opacity-50' : ''
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDot}`} />
          <h3 className="font-semibold text-wiesn-brown-dark truncate text-[13px] tracking-tight">
            {name}
          </h3>
        </div>
        <button
          onClick={handleToggle}
          role="switch"
          aria-checked={enabled}
          className={`toggle-switch flex-shrink-0 ${enabled ? 'active' : 'inactive'}`}
          aria-label={`${enabled ? 'Disable' : 'Enable'} ${name}`}
        />
      </div>

      {/* Type badge */}
      {snapshot?.portal_type && (
        <div className="mb-3">
          <StatusBadge type={snapshot.portal_type} />
        </div>
      )}

      {/* Stats */}
      <div className="space-y-2 text-[13px] text-wiesn-text-light">
        <div className="flex items-center gap-2">
          <Calendar className="w-3.5 h-3.5 text-wiesn-gold" aria-hidden="true" />
          <span>
            <strong className="text-wiesn-brown-dark tabular-nums">{datesCount}</strong> dates
          </span>
        </div>

        {snapshot?.timestamp && (
          <div className="flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 text-wiesn-blue/60" aria-hidden="true" />
            <span className="text-[11px] text-wiesn-text-muted">{formatTime(snapshot.timestamp)}</span>
          </div>
        )}

        {hasError && (
          <div className="flex items-center gap-2 text-wiesn-error">
            <AlertTriangle className="w-3.5 h-3.5" aria-hidden="true" />
            <span className="text-[11px] truncate">{snapshot?.error}</span>
          </div>
        )}
      </div>

      {/* Date chips */}
      {hasDate && (
        <div className="mt-3 pt-3 border-t border-wiesn-border-light">
          <div className="flex flex-wrap gap-1.5">
            {snapshot!.datum_options.slice(0, 4).map((d) => (
              <span
                key={d.value}
                className="text-[11px] bg-wiesn-gold/10 text-wiesn-brown px-2 py-0.5 rounded-md font-medium"
              >
                {d.text}
              </span>
            ))}
            {datesCount > 4 && (
              <span className="text-[11px] text-wiesn-text-muted">
                +{datesCount - 4}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
