import { useCallback, useEffect, useRef } from 'react';
import { useCallStore } from '../lib/call';
import { useTtsStore } from '../lib/tts';
import { transcribeAudio } from '../lib/api';

// Mirrors the CLI's record_until_silence (speech/voice_io.py): wait for
// speech to start, then cut the turn once it's been quiet for a bit. The
// thresholds are on normalized (0..1) RMS of 8-bit time-domain samples, not
// dBFS, so they're tuned empirically rather than to a physical unit.
const SPEECH_RMS_THRESHOLD = 0.035;
const SILENCE_RMS_THRESHOLD = 0.02;
const SILENCE_HOLD_MS = 900;
const STARTUP_SILENCE_MS = 7000;
const MAX_TURN_MS = 15000;

export const JARVIS_CALL_PERSONA =
  'Eres Jarvis, el asistente de IA personal al estilo del mayordomo de Tony ' +
  'Stark. Estás en una llamada de voz en tiempo real: responde siempre en ' +
  '1-3 frases breves, con tono formal, ingenioso y resolutivo — directo a ' +
  'la acción, sin rodeos ni disculpas innecesarias. Tu respuesta se va a ' +
  'leer en voz alta, así que evita listas, markdown o texto que no suene ' +
  'natural al hablarlo.';

function rms(data: Uint8Array): number {
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    const v = (data[i] - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / data.length);
}

/**
 * Drives a continuous, hands-free voice call: listen → detect the user went
 * quiet → transcribe → send → speak the reply → listen again, looping until
 * `end()` is called. `sendTurn` is supplied by the caller (InputArea) since
 * it needs that component's chat-sending logic (model, conversation id,
 * etc.); this hook only owns the audio plumbing and the turn-taking loop.
 */
export function useCallMode(sendTurn: (text: string) => Promise<string>) {
  const activeRef = useRef(false);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const sendTurnRef = useRef(sendTurn);
  sendTurnRef.current = sendTurn;

  useEffect(() => {
    const Ctor = (window as any).MediaRecorder;
    if (!Ctor || !navigator.mediaDevices?.getUserMedia) {
      useCallStore.getState().setSupported(false);
    }
  }, []);

  const stopLevelLoop = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  // Records one utterance on the call's shared mic stream. Resolves with a
  // Blob once speech was heard and then paused, or null if nothing was said
  // (startup timeout) or the call ended mid-turn.
  const recordTurn = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const stream = streamRef.current;
      const analyser = analyserRef.current;
      if (!stream || !analyser || !activeRef.current) {
        resolve(null);
        return;
      }

      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      let gotSpeech = false;
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };
      recorder.onstop = () => {
        stopLevelLoop();
        resolve(
          gotSpeech && chunks.length
            ? new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
            : null,
        );
      };

      let hasSpoken = false;
      let silenceSince: number | null = null;
      const startedAt = Date.now();
      const data = new Uint8Array(analyser.frequencyBinCount);

      const tick = () => {
        if (!activeRef.current) {
          if (recorder.state !== 'inactive') recorder.stop();
          return;
        }
        analyser.getByteTimeDomainData(data);
        const level = Math.min(1, rms(data) * 4);
        useCallStore.getState().setLevel(level);
        const now = Date.now();

        if (level > SPEECH_RMS_THRESHOLD) {
          hasSpoken = true;
          gotSpeech = true;
          silenceSince = null;
        } else if (hasSpoken && level < SILENCE_RMS_THRESHOLD) {
          if (silenceSince === null) silenceSince = now;
          else if (now - silenceSince > SILENCE_HOLD_MS) {
            recorder.stop();
            return;
          }
        } else {
          silenceSince = null;
        }

        if (!hasSpoken && now - startedAt > STARTUP_SILENCE_MS) {
          recorder.stop();
          return;
        }
        if (now - startedAt > MAX_TURN_MS) {
          recorder.stop();
          return;
        }
        rafRef.current = requestAnimationFrame(tick);
      };

      recorder.start();
      tick();
    });
  }, [stopLevelLoop]);

  const loop = useCallback(async () => {
    while (activeRef.current) {
      useCallStore.getState().setState('listening');
      const blob = await recordTurn();
      if (!activeRef.current) break;
      if (!blob) continue; // nothing said — keep listening

      useCallStore.getState().setState('thinking');
      useCallStore.getState().setLevel(0);
      let text = '';
      try {
        const result = await transcribeAudio(blob);
        text = result.text?.trim() ?? '';
      } catch {
        text = '';
      }
      if (!activeRef.current) break;
      if (!text) continue;

      let reply = '';
      try {
        reply = (await sendTurnRef.current(text)) ?? '';
      } catch {
        reply = '';
      }
      if (!activeRef.current) break;
      if (!reply) continue;

      useCallStore.getState().setState('speaking');
      await useTtsStore.getState().speak('call-reply', reply);
      // speak() resolves once playback *starts*, not once it ends.
      await new Promise<void>((resolve) => {
        if (useTtsStore.getState().state !== 'speaking') {
          resolve();
          return;
        }
        const unsubscribe = useTtsStore.subscribe((s) => {
          if (s.state !== 'speaking') {
            unsubscribe();
            resolve();
          }
        });
      });
    }
  }, [recordTurn]);

  const start = useCallback(async () => {
    if (activeRef.current) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyserRef.current = analyser;
      activeRef.current = true;
      useCallStore.getState().setActive(true);
      void loop();
    } catch {
      useCallStore.getState().setActive(false);
      useCallStore.getState().setSupported(false);
    }
  }, [loop]);

  const end = useCallback(() => {
    activeRef.current = false;
    stopLevelLoop();
    useTtsStore.getState().stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    analyserRef.current = null;
    useCallStore.getState().setState('idle');
    useCallStore.getState().setLevel(0);
    useCallStore.getState().setActive(false);
  }, [stopLevelLoop]);

  useEffect(() => {
    useCallStore.getState().setControls({ start, end });
    return () => {
      useCallStore.getState().setControls({ start: () => {}, end: () => {} });
    };
  }, [start, end]);

  // Hang up automatically if the component owning this hook unmounts
  // (e.g. navigating away mid-call) so the mic doesn't stay open.
  useEffect(() => () => end(), [end]);
}
