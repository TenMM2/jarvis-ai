import { Phone, PhoneOff } from 'lucide-react';

export type JarvisCoreState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface JarvisCoreProps {
  state: JarvisCoreState;
  size?: number;
  /**
   * Live 0..1 microphone amplitude. When provided while `state ===
   * 'listening'`, it drives the core's scale/brightness directly instead of
   * the fixed-rhythm CSS pulse — the call button reacting to how loud you
   * are actually talking, not a canned animation.
   */
  level?: number;
  /** Renders a phone icon and makes the core itself the call start/hang-up button. */
  onClick?: () => void;
  callActive?: boolean;
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
 * listening/thinking/speaking rather than two separate indicators. With
 * `onClick` it doubles as the call button, matching the "press the core to
 * start/end the call" concept.
 */
export function JarvisCore({ state, size = 80, level, onClick, callActive }: JarvisCoreProps) {
  const ringSize = size * 1.45;
  const liveReactive = state === 'listening' && typeof level === 'number';
  const coreScale = liveReactive ? 1 + Math.min(level!, 1) * 0.35 : undefined;
  const coreBrightness = liveReactive ? 1 + Math.min(level!, 1) * 0.6 : undefined;

  const core = (
    <div
      className="relative flex items-center justify-center shrink-0"
      style={{ width: ringSize, height: ringSize }}
      role={onClick ? 'button' : 'img'}
      aria-label={onClick ? (callActive ? 'End call with Jarvis' : 'Start call with Jarvis') : `Jarvis core: ${state}`}
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
          animation: liveReactive ? 'none' : ANIMATION_BY_STATE[state],
          transform: liveReactive ? `scale(${coreScale})` : undefined,
          filter: liveReactive ? `brightness(${coreBrightness})` : undefined,
          transition: liveReactive ? 'transform 60ms linear, filter 60ms linear' : undefined,
        }}
      />
      {onClick && (
        <div
          className="absolute inset-0 flex items-center justify-center pointer-events-none"
          style={{ color: 'white' }}
        >
          {callActive ? <PhoneOff size={size * 0.32} /> : <Phone size={size * 0.32} />}
        </div>
      )}
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

  if (!onClick) return core;

  return (
    <button
      type="button"
      onClick={onClick}
      className="cursor-pointer bg-transparent border-none p-0"
      title={callActive ? 'End call' : 'Start call with Jarvis'}
    >
      {core}
    </button>
  );
}
