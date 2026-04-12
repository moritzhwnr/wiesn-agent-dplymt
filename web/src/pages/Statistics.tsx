import { useEffect, useState } from 'react';
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { BarChart3, TrendingUp, Moon, Activity } from 'lucide-react';
import { api } from '../api';
import type { DailyStat, PortalStat, Summary } from '../api';

const chartColors = {
  blue: '#1a3f6f',
  gold: '#c9952a',
  brown: '#5c3520',
  success: '#16a34a',
  error: '#dc2626',
};

const gridStroke = '#f0e9da';
const tickStyle = { fontSize: 11, fill: '#9a8d82' };
const tooltipStyle = {
  background: 'white',
  border: '1px solid #f0e9da',
  borderRadius: '12px',
  boxShadow: '0 4px 12px -2px rgb(0 0 0 / 0.08)',
  padding: '8px 12px',
  fontSize: '12px',
};

export default function Statistics() {
  const [daily, setDaily] = useState<DailyStat[]>([]);
  const [portalStats, setPortalStats] = useState<PortalStat[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([api.getDailyStats(), api.getPortalStats(), api.getSummary()])
      .then(([d, p, s]) => { setDaily(d); setPortalStats(p); setSummary(s); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const topPortals = [...portalStats]
    .sort((a, b) => b.total_dates - a.total_dates)
    .slice(0, 15);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="skeleton h-8 w-48 rounded-lg" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton h-24 rounded-2xl" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="skeleton h-80 rounded-2xl" />
          <div className="skeleton h-80 rounded-2xl" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="animate-fade-in">
          <h1 className="text-2xl font-bold text-wiesn-brown-dark tracking-tight">Statistics</h1>
        </div>
        <div className="bg-wiesn-error/5 border border-wiesn-error/20 text-wiesn-error rounded-xl px-4 py-3 text-sm">
          Failed to load statistics: {error}
        </div>
      </div>
    );
  }

  const summaryCards = summary
    ? [
        { label: 'With dates', value: summary.portals_with_dates, icon: TrendingUp, color: 'text-wiesn-success', bg: 'bg-wiesn-success/8' },
        { label: 'Total dates', value: summary.total_dates_available, icon: BarChart3, color: 'text-wiesn-blue', bg: 'bg-wiesn-blue/8' },
        { label: 'Scan history', value: summary.history_records, icon: Activity, color: 'text-wiesn-gold', bg: 'bg-wiesn-gold/10' },
        { label: 'Errors', value: summary.scan_errors, icon: Moon, color: 'text-wiesn-error', bg: 'bg-wiesn-error/8' },
      ]
    : [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="animate-fade-in">
        <h1 className="text-2xl font-bold text-wiesn-brown-dark tracking-tight">
          Statistics
        </h1>
        <p className="text-wiesn-text-light text-sm mt-1">
          Scan results and trends
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 animate-fade-in animate-fade-in-delay-1">
        {summaryCards.map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="bg-white border border-wiesn-border-light rounded-2xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <div className={`w-7 h-7 rounded-lg ${bg} flex items-center justify-center`}>
                <Icon className={`w-3.5 h-3.5 ${color}`} />
              </div>
            </div>
            <p className="text-2xl font-bold text-wiesn-brown-dark tabular-nums tracking-tight">{value}</p>
            <p className="text-[11px] text-wiesn-text-muted uppercase tracking-wider mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Charts grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 animate-fade-in animate-fade-in-delay-2">
        {/* Neue Termine pro Tag */}
        <div className="bg-white border border-wiesn-border-light rounded-2xl p-6">
          <h2 className="text-[15px] font-semibold text-wiesn-brown-dark mb-5 tracking-tight">
            New dates per day
          </h2>
          {daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
                <XAxis dataKey="date" tick={tickStyle} tickFormatter={(v) => v.slice(5)} axisLine={false} tickLine={false} />
                <YAxis tick={tickStyle} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '8px' }} />
                <Line type="monotone" dataKey="new_dates" stroke={chartColors.gold} strokeWidth={2} dot={{ r: 3, fill: chartColors.gold }} name="New dates" />
                <Line type="monotone" dataKey="total_dates" stroke={chartColors.blue} strokeWidth={2} dot={{ r: 3, fill: chartColors.blue }} name="Total" />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[280px] flex items-center justify-center text-wiesn-text-muted text-sm">No data</div>
          )}
        </div>

        {/* Termine nach Portal */}
        <div className="bg-white border border-wiesn-border-light rounded-2xl p-6">
          <h2 className="text-[15px] font-semibold text-wiesn-brown-dark mb-5 tracking-tight">
            Dates by portal
          </h2>
          {topPortals.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={topPortals} layout="vertical" margin={{ left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} horizontal={false} />
                <XAxis type="number" tick={tickStyle} axisLine={false} tickLine={false} />
                <YAxis
                  type="category"
                  dataKey="portal"
                  tick={tickStyle}
                  width={120}
                  tickFormatter={(v: string) => v.length > 16 ? v.slice(0, 16) + '…' : v}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="total_dates" fill={chartColors.blue} radius={[0, 6, 6, 0]} name="Dates" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[280px] flex items-center justify-center text-wiesn-text-muted text-sm">No data</div>
          )}
        </div>

        {/* Abend-Slots über Zeit */}
        <div className="bg-white border border-wiesn-border-light rounded-2xl p-6 lg:col-span-2">
          <h2 className="text-[15px] font-semibold text-wiesn-brown-dark mb-5 tracking-tight">
            Evening slots over time
          </h2>
          {daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={daily}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
                <XAxis dataKey="date" tick={tickStyle} tickFormatter={(v) => v.slice(5)} axisLine={false} tickLine={false} />
                <YAxis tick={tickStyle} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '8px' }} />
                <Area
                  type="monotone"
                  dataKey="evening_slots"
                  stroke={chartColors.gold}
                  fill={chartColors.gold}
                  fillOpacity={0.12}
                  strokeWidth={2}
                  name="Evening slots"
                />
                <Area
                  type="monotone"
                  dataKey="errors"
                  stroke={chartColors.error}
                  fill={chartColors.error}
                  fillOpacity={0.06}
                  strokeWidth={1.5}
                  name="Errors"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[260px] flex items-center justify-center text-wiesn-text-muted text-sm">No data</div>
          )}
        </div>
      </div>
    </div>
  );
}
