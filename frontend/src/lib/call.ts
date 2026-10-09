import { create } from 'zustand';

export type CallState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface CallControls {
  start: () => void;
  end: () => void;
}

interface CallStore {
  state: CallState;
  /** Live 0..1 microphone amplitude while listening, for the reactive core. */
  level: number;
  isActive: boolean;
  supported: boolean;
  /** Last thing that went wrong (mic permission, transcription, network —
   * see useCallMode), shown in the HUD instead of silently doing nothing.
   * Cleared automatically at the start of the next successful turn. */
  error: string | null;
  controls: CallControls;
  setControls: (controls: CallControls) => void;
  setState: (state: CallState) => void;
  setLevel: (level: number) => void;
  setActive: (active: boolean) => void;
  setSupported: (supported: boolean) => void;
  setError: (error: string | null) => void;
}

const noop = () => {};

// The real engine (useCallMode) registers its start/end here once it mounts
// inside InputArea — the one place that already owns sendMessage. Other
// components (the hero core, a call button) just call
// useCallStore.getState().controls.start()/end() without needing to know
// where the implementation lives.
export const useCallStore = create<CallStore>((set) => ({
  state: 'idle',
  level: 0,
  isActive: false,
  supported: true,
  error: null,
  controls: { start: noop, end: noop },
  setControls: (controls) => set({ controls }),
  setState: (state) => set({ state }),
  setLevel: (level) => set({ level }),
  setActive: (isActive) => set({ isActive }),
  setSupported: (supported) => set({ supported }),
  setError: (error) => set({ error }),
}));
