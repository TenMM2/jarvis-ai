import { useCallback, useEffect, useRef, useState } from 'react';

// Vendor-prefixed SpeechRecognition isn't in lib.dom.d.ts; typed loosely
// rather than pulling in a whole ambient-types package for one browser API.
type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  const w = window as any;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** Strip accents so "jarvis" matches "járvis"/"jàrvis" misrecognitions. */
function normalize(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '');
}

/**
 * Continuous local wake-word listening for "Jarvis", via the browser's own
 * SpeechRecognition — not the Gemini backend. It's free, on-device, and
 * restartable indefinitely, which the Gemini mic flow (record → upload →
 * transcribe) is deliberately not: that path costs an API call per use and
 * is meant for a single deliberate utterance, not an always-on hot mic.
 *
 * `enabled` fully tears the recognizer down when false (settings toggle off,
 * or the caller pausing it during an active conversation turn) rather than
 * muting it, so there is never a hidden mic grant the user didn't ask for.
 */
export function useWakeWord(wakeWord: string, onWake: () => void, enabled: boolean) {
  const [supported, setSupported] = useState(true);
  const [active, setActive] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const onWakeRef = useRef(onWake);
  onWakeRef.current = onWake;
  const wakeWordRef = useRef(normalize(wakeWord));
  wakeWordRef.current = normalize(wakeWord);
  // Tracks whether *we* intend to be listening, so the onend auto-restart
  // doesn't resurrect a recognizer the caller just asked to stop.
  const wantActiveRef = useRef(false);

  useEffect(() => {
    if (!getSpeechRecognitionCtor()) setSupported(false);
  }, []);

  useEffect(() => {
    const Ctor = getSpeechRecognitionCtor();
    if (!enabled || !Ctor) {
      wantActiveRef.current = false;
      recognitionRef.current?.abort();
      recognitionRef.current = null;
      setActive(false);
      return;
    }

    wantActiveRef.current = true;
    const recognition = new Ctor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'es-ES';

    recognition.onresult = (event: any) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = normalize(event.results[i][0].transcript as string);
        if (transcript.includes(wakeWordRef.current)) {
          onWakeRef.current();
          return;
        }
      }
    };

    recognition.onerror = (event: any) => {
      // "no-speech"/"aborted" are routine on a continuous listener — the
      // onend handler below restarts it. Anything else (mic permission
      // revoked, hardware error) stops trying rather than spinning forever.
      if (event?.error !== 'no-speech' && event?.error !== 'aborted') {
        wantActiveRef.current = false;
        setActive(false);
      }
    };

    recognition.onend = () => {
      if (wantActiveRef.current) {
        try {
          recognition.start();
        } catch {
          // Already starting (rapid end/start race) — the next onend retries.
        }
      } else {
        setActive(false);
      }
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
      setActive(true);
    } catch {
      setActive(false);
    }

    return () => {
      wantActiveRef.current = false;
      recognition.onend = null;
      recognition.abort();
      if (recognitionRef.current === recognition) recognitionRef.current = null;
    };
  }, [enabled]);

  /** Pause listening for the duration of a conversation turn, then resume. */
  const pause = useCallback(() => {
    wantActiveRef.current = false;
    recognitionRef.current?.stop();
  }, []);

  const resume = useCallback(() => {
    if (!enabled || !recognitionRef.current) return;
    wantActiveRef.current = true;
    try {
      recognitionRef.current.start();
      setActive(true);
    } catch {
      // Already running.
    }
  }, [enabled]);

  return { supported, active, pause, resume };
}
