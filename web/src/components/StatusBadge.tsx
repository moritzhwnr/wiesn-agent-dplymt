interface StatusBadgeProps {
  type: string;
}

const typeColors: Record<string, { bg: string; text: string; dot: string }> = {
  livewire:   { bg: 'bg-purple-50', text: 'text-purple-600', dot: 'bg-purple-400' },
  wordpress:  { bg: 'bg-blue-50', text: 'text-blue-600', dot: 'bg-blue-400' },
  ratskeller: { bg: 'bg-amber-50', text: 'text-amber-600', dot: 'bg-amber-400' },
  custom_js:  { bg: 'bg-emerald-50', text: 'text-emerald-600', dot: 'bg-emerald-400' },
  shopify:    { bg: 'bg-green-50', text: 'text-green-600', dot: 'bg-green-400' },
  iframe:     { bg: 'bg-cyan-50', text: 'text-cyan-600', dot: 'bg-cyan-400' },
  static:     { bg: 'bg-gray-50', text: 'text-gray-500', dot: 'bg-gray-300' },
  unknown:    { bg: 'bg-gray-50', text: 'text-gray-400', dot: 'bg-gray-300' },
};

export default function StatusBadge({ type }: StatusBadgeProps) {
  const normalized = type?.toLowerCase().replace(/[\s-]/g, '_') ?? 'unknown';
  const colors = typeColors[normalized] ?? typeColors.unknown;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium ${colors.bg} ${colors.text}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${colors.dot}`} aria-hidden="true" />
      {type || 'unknown'}
    </span>
  );
}
