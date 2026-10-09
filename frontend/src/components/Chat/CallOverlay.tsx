import { JarvisVoiceScreen } from './JarvisVoiceScreen';
import { useCallStore } from '../../lib/call';
import { useAppStore } from '../../lib/store';

/**
 * Mounted once at the app root. In HUD mode (the default home experience)
 * this is permanently visible and covers the whole app, sidebar included —
 * "no chat, no distractions". If the user switches to classic text mode, it
 * only reappears as a full-screen takeover while a call is actually active,
 * same as before.
 */
export function CallOverlay() {
  const voiceHudMode = useAppStore((s) => s.settings.voiceHudMode);
  const isActive = useCallStore((s) => s.isActive);
  if (!voiceHudMode && !isActive) return null;
  return <JarvisVoiceScreen fullViewport showExitToText={voiceHudMode} />;
}
