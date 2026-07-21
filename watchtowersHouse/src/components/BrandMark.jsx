export default function BrandMark({ compact = false }) {
  return (
    <span className="inline-flex items-center gap-3">
      <span className="relative grid h-10 w-10 place-items-center rounded-xl border border-amber-300/25 bg-amber-300/10 shadow-[0_0_28px_rgba(251,191,36,0.14)]">
        <svg aria-hidden="true" viewBox="0 0 32 32" className="h-6 w-6 text-amber-300" fill="none">
          <path d="M16 3 7 8v7c0 6 3.8 11.3 9 14 5.2-2.7 9-8 9-14V8l-9-5Z" stroke="currentColor" strokeWidth="2" />
          <path d="M11 17h10M13 13h6M14 21h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-slate-950 bg-emerald-400" />
      </span>
      {!compact && (
        <span>
          <span className="block font-display text-sm font-semibold tracking-[0.18em] text-white">WATCHTOWER</span>
          <span className="block text-[0.62rem] uppercase tracking-[0.28em] text-slate-500">Control plane</span>
        </span>
      )}
    </span>
  );
}
