import { Palette } from 'lucide-react';
import { JarvisReactor, type HudTheme } from './JarvisReactor';
import { useCallStore } from '../../lib/call';
import { useAppStore } from '../../lib/store';

const CAPTION_BY_STATE: Record<string, string> = {
  idle: 'TAP TO CONNECT',
  listening: 'LISTENING',
  thinking: 'PROCESSING',
  speaking: 'SPEAKING',
};

/** A handful of bars whose heights fan out from `level` — a cheap stand-in
 * for a spectrum analyzer that still reads as "live audio" at a glance. */
function LevelBars({ level, color }: { level: number; color: string }) {
  const bars = [0.4, 0.75, 1, 0.75, 0.4];
  return (
    <div className="flex items-end gap-1" style={{ height: 24 }}>
      {bars.map((mult, i) => (
        <div
          key={i}
          style={{
            width: 3,
            height: `${Math.max(3, level * mult * 24)}px`,
            background: color,
            opacity: 0.4 + level * 0.6,
            transition: 'height 80ms linear',
          }}
        />
      ))}
    </div>
  );
}

interface JarvisVoiceScreenProps {
  fullViewport?: boolean;
  onHangUp?: () => void;
  /** Lets the user drop back to the classic text UI — hidden while a call
   * is active so it can't be used to dodge the hang-up flow by accident. */
  showExitToText?: boolean;
}

export function JarvisVoiceScreen({ fullViewport = false, onHangUp, showExitToText = false }: JarvisVoiceScreenProps) {
  const state = useCallStore((s) => s.state);
  const level = useCallStore((s) => s.level);
  const isActive = useCallStore((s) => s.isActive);
  const theme = useAppStore((s) => s.settings.hudTheme);
  const setTheme = (t: HudTheme) => useAppStore.getState().updateSettings({ hudTheme: t });
  const accent = theme === 'blue' ? '#00d2ff' : '#ffaa00';

  const handleCoreClick = () => {
    if (isActive) {
      useCallStore.getState().controls.end();
      onHangUp?.();
    } else {
      useCallStore.getState().controls.start();
    }
  };

  return (
    <div
      className={fullViewport ? 'fixed inset-0' : 'absolute inset-0'}
      style={{ background: '#000', zIndex: fullViewport ? 1000 : undefined }}
    >
      {/* Color scheme toggle */}
      <button
        onClick={() => setTheme(theme === 'blue' ? 'amber' : 'blue')}
        className="absolute top-4 right-4 p-2 rounded-full cursor-pointer"
        style={{ color: accent, opacity: 0.6, background: 'transparent', border: `1px solid ${accent}` }}
        title="Toggle HUD color scheme"
      >
        <Palette size={14} />
      </button>

      {/* Left HUD panel */}
      <div
        className="absolute left-6 top-1/2 -translate-y-1/2 font-mono text-[10px] tracking-widest"
        style={{ color: accent, opacity: 0.7 }}
      >
        <div className="mb-2">STATUS</div>
        <div className="mb-3" style={{ opacity: 0.9, fontSize: 12 }}>
          {CAPTION_BY_STATE[state] ?? 'IDLE'}
        </div>
        <LevelBars level={state === 'idle' ? 0 : level} color={accent} />
      </div>

      {/* Right HUD panel */}
      <div
        className="absolute right-6 top-1/2 -translate-y-1/2 font-mono text-[10px] tracking-widest text-right"
        style={{ color: accent, opacity: 0.7 }}
      >
        <div className="mb-2">LINK</div>
        <div style={{ opacity: 0.9, fontSize: 12 }}>{isActive ? 'ONLINE' : 'STANDBY'}</div>
      </div>

      <div className="h-full w-full flex flex-col items-center justify-center gap-5">
        <div onClick={handleCoreClick} className="cursor-pointer">
          <JarvisReactor state={state} level={level} theme={theme} size={fullViewport ? 150 : 180} />
        </div>
        <p className="text-[11px] font-mono tracking-widest" style={{ color: accent, opacity: 0.5 }}>
          {isActive ? 'TAP CORE TO DISCONNECT' : 'TAP CORE TO CONNECT'}
        </p>
        {showExitToText && !isActive && (
          <button
            onClick={() => useAppStore.getState().updateSettings({ voiceHudMode: false })}
            className="text-[10px] font-mono tracking-widest cursor-pointer underline"
            style={{ color: accent, opacity: 0.35, background: 'transparent', border: 'none' }}
          >
            SWITCH TO TEXT MODE
          </button>
        )}
      </div>
    </div>
  );
}
