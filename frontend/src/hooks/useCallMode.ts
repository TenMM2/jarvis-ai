import { useCallback, useEffect, useRef } from 'react';
import { useCallStore } from '../lib/call';
import { useTtsStore, getActiveAudioElement } from '../lib/tts';
import { transcribeAudio } from '../lib/api';

// Mirrors the CLI's record_until_silence (speech/voice_io.py): wait for
// speech to start, then cut the turn once it's been quiet for a bit. The
// thresholds are on normalized (0..1) RMS of 8-bit time-domain samples, not
// dBFS, so they're tuned empirically rather than to a physical unit.
// Fixed fallbacks — overridden per-call by the noise-floor calibration done
// in start(), since a hardcoded absolute RMS threshold turned out not to
// survive different mics/gain/room noise: a value tuned on one machine
// silently never triggered on another (recordTurn would just time out every
// 7s with "nothing heard", which looks identical to the call being stuck).
const SPEECH_RMS_THRESHOLD = 0.035;
const SILENCE_RMS_THRESHOLD = 0.02;
const SILENCE_HOLD_MS = 900;
const STARTUP_SILENCE_MS = 7000;
const MAX_TURN_MS = 15000;
const NOISE_FLOOR_CALIBRATION_MS = 400;

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
  // Separate rAF handle for the barge-in watcher, which runs concurrently
  // with monitorPlaybackLevel's loop (both active while state === 'speaking')
  // and must not cancel each other via a shared ref.
  const bargeRafRef = useRef<number | null>(null);
  const sendTurnRef = useRef(sendTurn);
  sendTurnRef.current = sendTurn;
  // Ambient noise floor measured fresh for each call (see calibrateNoiseFloor
  // in start()); thresholds below are derived from it instead of fixed
  // constants, so a noisier room or a hotter mic gain doesn't just silently
  // never trigger speech detection.
  const noiseFloorRef = useRef(0.01);
  const speechThreshold = useCallback(
    () => Math.max(SPEECH_RMS_THRESHOLD, noiseFloorRef.current * 2.5),
    [],
  );
  const silenceThreshold = useCallback(
    () => Math.max(SILENCE_RMS_THRESHOLD, noiseFloorRef.current * 1.4),
    [],
  );

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

  // While Jarvis's reply plays, tap an analyser onto the *actual* TTS audio
  // element so the core's "speaking" animation tracks the real voice output
  // instead of a fixed-rhythm CSS pulse — same idea as the mic-level loop in
  // recordTurn(), just wired to playback instead of capture. Each turn gets a
  // fresh <audio> element (see lib/tts.ts), so a fresh source node per call
  // is correct, not a leak of a reused one.
  const monitorPlaybackLevel = useCallback(() => {
    const ctx = audioCtxRef.current;
    const el = getActiveAudioElement();
    if (!ctx || !el) return;

    let source: MediaElementAudioSourceNode;
    try {
      source = ctx.createMediaElementSource(el);
    } catch {
      return; // already tapped (shouldn't happen — new element per turn)
    }
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    source.connect(ctx.destination); // keep audio audible through this graph
    const data = new Uint8Array(analyser.frequencyBinCount);

    const tick = () => {
      if (!activeRef.current || useTtsStore.getState().state !== 'speaking') {
        stopLevelLoop();
        useCallStore.getState().setLevel(0);
        source.disconnect();
        return;
      }
      analyser.getByteTimeDomainData(data);
      useCallStore.getState().setLevel(Math.min(1, rms(data) * 4));
      rafRef.current = requestAnimationFrame(tick);
    };
    tick();
  }, [stopLevelLoop]);

  // Barge-in: while Jarvis is speaking, keep watching the *mic* (not the
  // playback analyser) for the user starting to talk over it. On the first
  // sustained bit of speech, resolve 'bargein' so the loop can cut TTS
  // immediately and go straight back to listening — "if I start talking,
  // Jarvis shuts up". Requires a few consecutive frames above threshold so
  // a single click/pop in the mic doesn't trigger a false interrupt.
  const waitForSpeakEndOrBargeIn = useCallback((): Promise<'ended' | 'bargein'> => {
    return new Promise((resolve) => {
      if (useTtsStore.getState().state !== 'speaking') {
        resolve('ended');
        return;
      }
      let settled = false;
      const finish = (result: 'ended' | 'bargein') => {
        if (settled) return;
        settled = true;
        unsubscribe();
        if (bargeRafRef.current !== null) {
          cancelAnimationFrame(bargeRafRef.current);
          bargeRafRef.current = null;
        }
        resolve(result);
      };

      const unsubscribe = useTtsStore.subscribe((s) => {
        if (s.state !== 'speaking') finish('ended');
      });

      const analyser = analyserRef.current;
      if (!analyser) return; // no mic graph — fall back to natural end only
      const data = new Uint8Array(analyser.frequencyBinCount);
      let speechFrames = 0;
      const tick = () => {
        if (settled || !activeRef.current) return;
        analyser.getByteTimeDomainData(data);
        if (rms(data) * 4 > speechThreshold()) {
          speechFrames += 1;
          if (speechFrames > 2) {
            console.log('[jarvis-call] barge-in detected — cutting Jarvis off');
            finish('bargein');
            return;
          }
        } else {
          speechFrames = 0;
        }
        bargeRafRef.current = requestAnimationFrame(tick);
      };
      tick();
    });
  }, [speechThreshold]);

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
      const speechCutoff = speechThreshold();
      const silenceCutoff = silenceThreshold();
      let lastLevelLogAt = 0;
      console.log('[jarvis-call] recording turn — thresholds', {
        speech: speechCutoff.toFixed(4),
        silence: silenceCutoff.toFixed(4),
      });

      const tick = () => {
        if (!activeRef.current) {
          if (recorder.state !== 'inactive') recorder.stop();
          return;
        }
        analyser.getByteTimeDomainData(data);
        const level = Math.min(1, rms(data) * 4);
        useCallStore.getState().setLevel(level);
        const now = Date.now();

        if (now - lastLevelLogAt > 500) {
          lastLevelLogAt = now;
          console.log('[jarvis-call] level', level.toFixed(4), hasSpoken ? '(speaking)' : '(waiting for speech)');
        }

        if (level > speechCutoff) {
          if (!hasSpoken) console.log('[jarvis-call] audio chunk captured — speech detected');
          hasSpoken = true;
          gotSpeech = true;
          silenceSince = null;
        } else if (hasSpoken && level < silenceCutoff) {
          if (silenceSince === null) silenceSince = now;
          else if (now - silenceSince > SILENCE_HOLD_MS) {
            console.log('[jarvis-call] silence detected -> sending to STT');
            recorder.stop();
            return;
          }
        } else {
          silenceSince = null;
        }

        if (!hasSpoken && now - startedAt > STARTUP_SILENCE_MS) {
          console.log('[jarvis-call] startup timeout — nothing heard, still listening');
          recorder.stop();
          return;
        }
        if (now - startedAt > MAX_TURN_MS) {
          console.log('[jarvis-call] max turn length reached -> sending to STT');
          recorder.stop();
          return;
        }
        rafRef.current = requestAnimationFrame(tick);
      };

      recorder.start();
      tick();
    });
  }, [stopLevelLoop, speechThreshold, silenceThreshold]);

  const loop = useCallback(async () => {
    while (activeRef.current) {
      console.log('[jarvis-call] listening...');
      useCallStore.getState().setState('listening');
      useCallStore.getState().setError(null);
      const blob = await recordTurn();
      if (!activeRef.current) break;
      if (!blob) {
        console.log('[jarvis-call] nothing heard — still listening');
        continue; // nothing said — keep listening
      }
      console.log('[jarvis-call] turn captured', { bytes: blob.size });

      useCallStore.getState().setState('thinking');
      useCallStore.getState().setLevel(0);
      let text = '';
      try {
        const result = await transcribeAudio(blob);
        text = result.text?.trim() ?? '';
        console.log('[jarvis-call] STT received:', JSON.stringify(text));
      } catch (err) {
        console.error('[jarvis-call] transcription failed', err);
        useCallStore.getState().setError(
          err instanceof Error ? `Transcription failed: ${err.message}` : 'Transcription failed',
        );
        text = '';
      }
      if (!activeRef.current) break;
      if (!text) continue;

      let reply = '';
      try {
        reply = (await sendTurnRef.current(text)) ?? '';
        console.log('[jarvis-call] reply:', JSON.stringify(reply));
      } catch (err) {
        console.error('[jarvis-call] sendTurn failed', err);
        useCallStore.getState().setError(
          err instanceof Error ? `Request failed: ${err.message}` : 'Request failed',
        );
        reply = '';
      }
      if (!activeRef.current) break;
      if (!reply) continue;

      useCallStore.getState().setState('speaking');
      console.log('[jarvis-call] speaking...');
      // speak() never throws — on failure it swallows the error into its own
      // store and leaves state as 'idle' instead of 'speaking'. Check that
      // directly rather than try/catch, otherwise a synthesis failure looks
      // exactly like "Jarvis just didn't say anything" with no clue why.
      await useTtsStore.getState().speak('call-reply', reply);
      const ttsAfterSpeak = useTtsStore.getState();
      if (ttsAfterSpeak.state !== 'speaking') {
        console.error('[jarvis-call] TTS playback failed', ttsAfterSpeak.error);
        useCallStore.getState().setError(
          ttsAfterSpeak.error ? `Voice playback failed: ${ttsAfterSpeak.error}` : 'Voice playback failed',
        );
        continue;
      }
      console.log('[jarvis-call] playing audio response');
      // speak() resolves once playback *starts*, not once it ends — that's
      // exactly when the <audio> element exists and can be tapped.
      monitorPlaybackLevel();
      const result = await waitForSpeakEndOrBargeIn();
      if (result === 'bargein') {
        useTtsStore.getState().stop(); // cut Jarvis off immediately
        useCallStore.getState().setLevel(0);
      }
      // Either way, loop back to 'listening' next iteration — on a natural
      // end that's the normal turn-taking; on a barge-in it's the point of
      // the feature (the words spoken during the cut itself aren't
      // captured, only what follows, same as most hands-free assistants).
    }
  }, [recordTurn, monitorPlaybackLevel, waitForSpeakEndOrBargeIn]);

  const start = useCallback(async () => {
    if (activeRef.current) return;
    console.log('[jarvis-call] start() — requesting microphone permission');
    useCallStore.getState().setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      console.error('[jarvis-call] getUserMedia unavailable (insecure context or unsupported browser)');
      useCallStore.getState().setError('Microphone API unavailable in this browser/context');
      useCallStore.getState().setSupported(false);
      return;
    }
    try {
      // echoCancellation matters a lot more here than in turn-based mode:
      // with barge-in, Jarvis's own voice coming back through the speakers
      // and into the mic can otherwise trigger a false self-interruption.
      // noiseSuppression/autoGainControl are deliberately left off: on at
      // least one real setup they flattened the mic signal enough that
      // actual speech never crossed the fixed RMS threshold below, and the
      // call just looked "stuck" on LISTENING forever.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true },
      });
      console.log('[jarvis-call] microphone permission granted');
      streamRef.current = stream;
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyserRef.current = analyser;

      // Calibrate the noise floor against this room/mic before judging any
      // real speech, so the speech/silence thresholds adapt instead of
      // relying on a constant tuned on someone else's machine.
      await new Promise<void>((resolve) => {
        const data = new Uint8Array(analyser.frequencyBinCount);
        const samples: number[] = [];
        const startedAt = performance.now();
        const sample = () => {
          analyser.getByteTimeDomainData(data);
          samples.push(rms(data));
          if (performance.now() - startedAt < NOISE_FLOOR_CALIBRATION_MS) {
            requestAnimationFrame(sample);
          } else {
            const avg = samples.reduce((a, b) => a + b, 0) / Math.max(1, samples.length);
            noiseFloorRef.current = avg;
            console.log('[jarvis-call] noise floor calibrated:', avg.toFixed(4));
            resolve();
          }
        };
        sample();
      });

      activeRef.current = true;
      useCallStore.getState().setActive(true);
      void loop();
    } catch (err) {
      console.error('[jarvis-call] getUserMedia failed', err);
      const name = err instanceof DOMException ? err.name : '';
      const message =
        name === 'NotAllowedError'
          ? 'Microphone permission denied — allow it in the browser address bar and tap again'
          : name === 'NotFoundError'
          ? 'No microphone found'
          : err instanceof Error
          ? err.message
          : 'Could not access the microphone';
      useCallStore.getState().setError(message);
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
