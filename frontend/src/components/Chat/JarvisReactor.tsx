import type { JarvisCoreState } from './JarvisCore';

export type HudTheme = 'blue' | 'amber';

const THEME_COLORS: Record<HudTheme, { core: string; coreDim: string; glow: string }> = {
  blue: { core: '#00d2ff', coreDim: '#0055ff', glow: 'rgba(0, 170, 255, 0.55)' },
  amber: { core: '#ffaa00', coreDim: '#ff3300', glow: 'rgba(255, 140, 0, 0.55)' },
};

interface JarvisReactorProps {
  state: JarvisCoreState;
  level: number;
  theme: HudTheme;
  size?: number;
}

/**
 * The holographic reactor: core + two counter-rotating orbital rings + a
 * ticked platform disc, all driven by `level` (0..1, mic or playback RMS —
 * whichever is live for the current state) rather than a fixed rhythm. Pure
 * CSS/SVG — no Three.js: at this screen size a WebGL scene would add real
 * bundle weight and a second render pipeline to keep in sync with the DOM
 * HUD panels, for a result a few rotating rings already deliver.
 */
export function JarvisReactor({ state, level, theme, size = 220 }: JarvisReactorProps) {
  const c = THEME_COLORS[theme];
  const l = Math.min(1, Math.max(0, level));
  const active = state === 'listening' || state === 'speaking';
  const coreScale = active ? 1 + l * 0.22 : state === 'thinking' ? 1.04 : 1;
  const ringSpeedBoost = active ? 1 + l * 2.2 : 1;
  const platformSize = size * 1.9;

  return (
    <div
      className="relative flex items-center justify-center shrink-0"
      style={{ width: platformSize, height: platformSize }}
    >
      {/* Platform disc */}
      <svg
        width={platformSize}
        height={platformSize * 0.42}
        viewBox="0 0 200 84"
        className="absolute"
        style={{ bottom: 0, opacity: 0.55 }}
      >
        <ellipse cx="100" cy="42" rx="98" ry="40" fill="none" stroke={c.core} strokeWidth="0.75" opacity="0.5" />
        <ellipse cx="100" cy="42" rx="78" ry="31" fill="none" stroke={c.core} strokeWidth="0.5" opacity="0.35" />
        {Array.from({ length: 24 }).map((_, i) => {
          const angle = (i / 24) * Math.PI * 2;
          const rx1 = 98, ry1 = 40, rx2 = 90, ry2 = 36.5;
          return (
            <line
              key={i}
              x1={100 + rx1 * Math.cos(angle)}
              y1={42 + ry1 * Math.sin(angle)}
              x2={100 + rx2 * Math.cos(angle)}
              y2={42 + ry2 * Math.sin(angle)}
              stroke={c.core}
              strokeWidth="0.75"
              opacity="0.4"
            />
          );
        })}
      </svg>

      {/* Orbital rings */}
      <div
        className="absolute rounded-full"
        style={{
          width: size * 1.55,
          height: size * 1.55,
          border: `1px solid ${c.core}`,
          opacity: 0.3,
          animation: `jarvis-ring-spin ${8 / ringSpeedBoost}s linear infinite`,
          boxShadow: `0 0 ${12 + l * 20}px ${c.glow}`,
        }}
      />
      <div
        className="absolute rounded-full"
        style={{
          width: size * 1.3,
          height: size * 1.3,
          border: `1px dashed ${c.core}`,
          opacity: 0.4,
          animation: `jarvis-ring-spin-reverse ${6 / ringSpeedBoost}s linear infinite`,
        }}
      />

      {/* Core */}
      <div
        className="rounded-full relative"
        style={{
          width: size,
          height: size,
          background: `radial-gradient(circle at 35% 30%, rgba(255,255,255,0.45), ${c.core} 50%, ${c.coreDim} 100%)`,
          boxShadow: `0 0 ${size * 0.4}px ${size * 0.15}px ${c.glow}`,
          transform: `scale(${coreScale})`,
          transition: 'transform 70ms linear, box-shadow 120ms linear',
        }}
      />

      {/* "J.A.R.V.I.S." label */}
      <div
        className="absolute font-mono text-[11px] tracking-[0.35em]"
        style={{ bottom: -platformSize * 0.08, color: c.core, opacity: 0.75, textShadow: `0 0 8px ${c.glow}` }}
      >
        J.A.R.V.I.S.
      </div>

      <style>{`
        @keyframes jarvis-ring-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes jarvis-ring-spin-reverse { from { transform: rotate(360deg); } to { transform: rotate(0deg); } }
      `}</style>
    </div>
  );
}
