import { useEffect, useState } from 'react';
import { Search, Beer } from 'lucide-react';
import { api } from '../api';
import type { Portal } from '../api';
import PortalCard from '../components/PortalCard';

type FilterMode = 'all' | 'enabled' | 'with-dates';

export default function Portals() {
  const [portals, setPortals] = useState<Portal[]>([]);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<FilterMode>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api.getPortals()
      .then(setPortals)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleToggle = (name: string, enabled: boolean) => {
    setPortals((prev) =>
      prev.map((p) => (p.name === name ? { ...p, enabled } : p))
    );
  };

  const filtered = portals.filter((p) => {
    if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === 'enabled' && !p.enabled) return false;
    if (filter === 'with-dates' && !(p.snapshot?.datum_options?.length)) return false;
    return true;
  });

  const counts = {
    all: portals.length,
    enabled: portals.filter((p) => p.enabled).length,
    'with-dates': portals.filter((p) => (p.snapshot?.datum_options?.length ?? 0) > 0).length,
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="animate-fade-in">
        <h1 className="text-2xl font-bold text-wiesn-brown-dark tracking-tight">
          Portals
        </h1>
        <p className="text-wiesn-text-light text-sm mt-1">
          {portals.length} booking portals configured
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 animate-fade-in animate-fade-in-delay-1">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-wiesn-text-muted" aria-hidden="true" />
          <input
            type="text"
            name="portal-search"
            placeholder="Search portals…"
            aria-label="Search portals"
            autoComplete="off"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 bg-white border border-wiesn-border-light rounded-xl text-sm text-wiesn-text placeholder:text-wiesn-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-wiesn-gold/30 focus-visible:border-wiesn-gold/50 transition-colors"
          />
        </div>

        {/* Filter buttons */}
        <div className="flex gap-1 bg-white border border-wiesn-border-light rounded-xl p-1">
          {([
            { key: 'all' as FilterMode, label: 'All' },
            { key: 'enabled' as FilterMode, label: 'Active' },
            { key: 'with-dates' as FilterMode, label: 'With dates' },
          ]).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              aria-pressed={filter === key}
              className={`px-3.5 py-1.5 rounded-lg text-[13px] font-medium transition-colors duration-150 ${
                filter === key
                  ? 'bg-wiesn-gold/15 text-wiesn-gold-dark shadow-sm'
                  : 'text-wiesn-text-muted hover:text-wiesn-text-light hover:bg-wiesn-cream/60'
              }`}
            >
              {label} ({counts[key]})
            </button>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-wiesn-error/5 border border-wiesn-error/20 text-wiesn-error rounded-xl px-4 py-3 text-sm animate-fade-in">
          Failed to load portals: {error}
        </div>
      )}

      {/* Grid */}
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="skeleton h-48 rounded-2xl" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-white border border-wiesn-border-light rounded-2xl p-10 text-center">
          <div className="w-12 h-12 rounded-xl bg-wiesn-blue/8 flex items-center justify-center mx-auto mb-3">
            <Beer className="w-6 h-6 text-wiesn-blue" />
          </div>
          <p className="text-sm text-wiesn-text-light">
            No portals found
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 animate-fade-in animate-fade-in-delay-2">
          {filtered.map((p) => (
            <PortalCard key={p.name} portal={p} onToggle={handleToggle} />
          ))}
        </div>
      )}
    </div>
  );
}
