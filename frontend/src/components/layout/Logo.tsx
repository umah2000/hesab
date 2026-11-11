export function Logo({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden>
      <defs>
        <linearGradient id="nc-g1" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="oklch(0.74 0.13 200)" />
          <stop offset="1" stopColor="oklch(0.5 0.2 262)" />
        </linearGradient>
        <linearGradient id="nc-g2" x1="1" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="oklch(0.86 0.1 190)" />
          <stop offset="1" stopColor="oklch(0.6 0.17 255)" />
        </linearGradient>
      </defs>
      <path d="M24 3 42 13.5v21L24 45 6 34.5v-21Z" fill="url(#nc-g1)" />
      <path d="M24 12.5 33.5 18v12L24 35.5 14.5 30V18Z" fill="url(#nc-g2)" opacity=".9" />
      <path d="M19.5 28.5v-9l9 9v-9" fill="none" stroke="white" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
