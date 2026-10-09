import { JarvisCore } from './JarvisCore';
import { useCallStore } from '../../lib/call';

const CAPTION_BY_STATE: Record<string, string> = {
  idle: 'Connecting...',
  listening: 'Listening...',
  thinking: 'Thinking...',
  speaking: 'Speaking...',
};

/**
 * Full-screen black call view. Mounted once at the app root and shown
 * whenever a call is active, so starting a call from anywhere (hero core or
 * the inline core in the input bar) takes over the whole screen rather than
 * just swapping the small core's icon in place.
 */
export function CallOverlay() {
  const isActive = useCallStore((s) => s.isActive);
  const state = useCallStore((s) => s.state);
  const level = useCallStore((s) => s.level);

  if (!isActive) return null;

  return (
    <div
      className="fixed inset-0 flex flex-col items-center justify-center gap-6"
      style={{ background: '#000', zIndex: 1000 }}
    >
      <JarvisCore
        size={140}
        state={state}
        level={level}
        callActive
        onClick={() => useCallStore.getState().controls.end()}
      />
      <p className="text-sm" style={{ color: 'rgba(255,255,255,0.55)' }}>
        {CAPTION_BY_STATE[state] ?? ''}
      </p>
      <p className="text-xs" style={{ color: 'rgba(255,255,255,0.3)' }}>
        Tap the core to hang up
      </p>
    </div>
  );
}
