/**
 * The login page's illustration: a report sheet with bars and a pie, a rising arrow,
 * a calculator and a pen. Drawn here (no image file, no CDN) in the theme's colours.
 */
export function LoginArt({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 560 360" className={className} role="img" aria-label="نمودار رشد فروش روی میز کار">
      <defs>
        <linearGradient id="la-bar" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="oklch(0.82 0.11 210)" />
          <stop offset="1" stopColor="oklch(0.56 0.2 261)" />
        </linearGradient>
        <linearGradient id="la-arrow" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="oklch(0.8 0.1 210)" stopOpacity=".55" />
          <stop offset="1" stopColor="oklch(0.74 0.13 186)" />
        </linearGradient>
        <linearGradient id="la-calc" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="oklch(0.36 0.11 262)" />
          <stop offset="1" stopColor="oklch(0.22 0.08 265)" />
        </linearGradient>
        <linearGradient id="la-paper" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="white" />
          <stop offset="1" stopColor="oklch(0.95 0.02 250)" />
        </linearGradient>
        <filter id="la-shadow" x="-20%" y="-20%" width="140%" height="160%">
          <feDropShadow dx="0" dy="10" stdDeviation="10" floodColor="oklch(0.3 0.1 262)" floodOpacity=".18" />
        </filter>
      </defs>

      {/* desk */}
      <ellipse cx="280" cy="318" rx="260" ry="26" fill="oklch(0.6 0.12 255)" opacity=".08" />

      {/* report sheet */}
      <g filter="url(#la-shadow)" transform="rotate(-6 300 250)">
        <rect x="150" y="190" width="330" height="120" rx="10" fill="url(#la-paper)" />
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <rect key={i} x={175 + i * 22} y={280 - (i * 9 + 18)} width="13" height={i * 9 + 18} rx="3" fill="oklch(0.56 0.2 261)" opacity={0.55 + i * 0.07} />
        ))}
        <line x1="170" y1="282" x2="310" y2="282" stroke="oklch(0.8 0.03 255)" strokeWidth="2" />
        <circle cx="405" cy="245" r="40" fill="oklch(0.7 0.13 245)" />
        <path d="M405 245 L405 205 A40 40 0 0 1 444 237 Z" fill="oklch(0.5 0.2 262)" />
        <path d="M405 245 L444 237 A40 40 0 0 1 425 280 Z" fill="oklch(0.82 0.1 210)" />
        <rect x="175" y="205" width="80" height="6" rx="3" fill="oklch(0.85 0.03 255)" />
      </g>

      {/* growth bars and arrow */}
      <g>
        {[0, 1, 2, 3, 4, 5].map((i) => {
          const h = [46, 70, 58, 92, 80, 122][i];
          return <rect key={i} x={240 + i * 40} y={210 - h} width="26" height={h} rx="5" fill="url(#la-bar)" opacity=".92" />;
        })}
        <path
          d="M228 168 L282 128 L318 146 L372 92 L404 108 L462 46"
          fill="none"
          stroke="url(#la-arrow)"
          strokeWidth="14"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M444 36 L486 30 L474 72 Z" fill="oklch(0.74 0.13 186)" />
      </g>

      {/* calculator */}
      <g filter="url(#la-shadow)" transform="rotate(10 110 250)">
        <rect x="40" y="190" width="150" height="105" rx="14" fill="url(#la-calc)" />
        <rect x="54" y="202" width="122" height="22" rx="5" fill="oklch(0.86 0.06 200)" />
        {[0, 1, 2].map((r) =>
          [0, 1, 2, 3].map((c) => (
            <rect
              key={`${r}-${c}`}
              x={54 + c * 31}
              y={232 + r * 20}
              width="24"
              height="14"
              rx="4"
              fill={r === 2 && c === 3 ? "oklch(0.74 0.13 186)" : "oklch(0.48 0.1 262)"}
            />
          )),
        )}
      </g>

      {/* pen */}
      <g transform="rotate(14 330 320)">
        <rect x="230" y="314" width="200" height="9" rx="4.5" fill="oklch(0.27 0.08 263)" />
        <rect x="300" y="313" width="10" height="11" rx="2" fill="oklch(0.85 0.02 255)" />
        <path d="M430 314 L446 318.5 L430 323 Z" fill="oklch(0.6 0.02 255)" />
      </g>
    </svg>
  );
}
