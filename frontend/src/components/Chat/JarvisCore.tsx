export type JarvisCoreState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface JarvisCoreProps {
  state: JarvisCoreState;
  size?: number;
}

// One rhythm per state: idle breathes slowly, listening pulses attentively,
// thinking spins its ring, speaking flickers brightness like a VU meter.
const ANIMATION_BY_STATE: Record<JarvisCoreState, string> = {
  idle: 'jarvis-core-breathe 3.6s ease-in-out infinite',
  listening: 'jarvis-core-pulse 1.1s ease-in-out infinite',
  thinking: 'jarvis-core-pulse 0.7s ease-in-out infinite',
  speaking: 'jarvis-core-speak 0.45s ease-in-out infinite',
};

/**
 * The glowing blue core — this app's Jarvis-style visual identity. Reused at
 * two sizes: large in the empty-chat hero, small inline next to the mic
 * button, both driven by the same state so the whole UI reads as one thing
 * listening/thinking/speaking rather than two separate indicators.
 */
export function JarvisCore({ state, size = 80 }: JarvisCoreProps) {
  const ringSize = size * 1.45;

  return (
    <div
      className="relative flex items-center justify-center shrink-0"
      style={{ width: ringSize, height: ringSize }}
      role="img"
      aria-label={`Jarvis core: ${state}`}
    >
      {state === 'thinking' && (
        <div
          className="absolute rounded-full"
          style={{
            width: ringSize,
            height: ringSize,
            border: '2px solid transparent',
            borderTopColor: 'var(--color-accent)',
            borderRightColor: 'var(--color-accent)',
            animation: 'jarvis-core-spin 0.9s linear infinite',
          }}
        />
      )}
      <div
        className="rounded-full"
        style={{
          width: size,
          height: size,
          background:
            'radial-gradient(circle at 35% 30%, rgba(255,255,255,0.35), var(--color-accent) 55%, var(--color-accent-hover) 100%)',
          boxShadow: `0 0 ${size * 0.35}px ${size * 0.12}px var(--color-accent-glow)`,
          animation: ANIMATION_BY_STATE[state],
        }}
      />
      <style>{`
        @keyframes jarvis-core-breathe {
          0%, 100% { transform: scale(1); filter: brightness(1); }
          50% { transform: scale(1.04); filter: brightness(1.12); }
        }
        @keyframes jarvis-core-pulse {
          0%, 100% { transform: scale(1); filter: brightness(1); }
          50% { transform: scale(1.12); filter: brightness(1.3); }
        }
        @keyframes jarvis-core-speak {
          0%, 100% { transform: scale(1); filter: brightness(1.05); }
          50% { transform: scale(1.07); filter: brightness(1.4); }
        }
        @keyframes jarvis-core-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
