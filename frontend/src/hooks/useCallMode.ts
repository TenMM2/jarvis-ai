import { useCallback, useEffect, useRef } from 'react';
import { useCallStore } from '../lib/call';
import { useTtsStore, getActiveAudioElement } from '../lib/tts';
import { transcribeAudio } from '../lib/api';
import { useAppStore } from '../lib/store';

// Mirrors the CLI's record_until_silence (speech/voice_io.py): wait for
// speech to start, then cut the turn once it's been quiet for a bit.
// Levels are raw float RMS (0..1, see readRms) and the thresholds are
// *relative to the room*: they're derived from a noise floor measured at the
// start of each call, because absolute constants kept failing on real mics —
// one user's quiet array mic peaks around 0.005 while another's is 10x that.
// These constants are only minimums so a perfectly silent floor can't make
// the detector hair-trigger.
const MIN_SPEECH_RMS = 0.0025;
const MIN_SILENCE_RMS = 0.0012;
const SPEECH_OVER_FLOOR = 3.5; // speech starts at floor * this
const SILENCE_OVER_FLOOR = 1.8; // "quiet again" is floor * this...
const SILENCE_PEAK_FRACTION = 0.2; // ...or 20% of this turn's loudest moment
const SILENCE_HOLD_MS = 800;
const STARTUP_SILENCE_MS = 7000;
// Lowered from 15s: a real turn that reaches this is almost always a silence
// cutoff that failed to fire, not someone actually talking for 10+ seconds
// straight — better to cut losses (and the request-size/quota cost of a
// needlessly long recording) than wait out the old ceiling.
const MAX_TURN_MS = 10000;
const NOISE_FLOOR_WARMUP_MS = 300; // ignore the mic's start-up settling
const NOISE_FLOOR_CALIBRATION_MS = 700;

export const JARVIS_CALL_PERSONA =
  'Eres Jarvis, el asistente de IA personal al estilo del mayordomo de Tony ' +
  'Stark. Estás en una llamada de voz en tiempo real: responde SIEMPRE en ' +
  '1 o 2 frases muy cortas y directas, con tono formal, ingenioso y ' +
  'resolutivo — nunca más de 2 frases, sin rodeos ni disculpas ' +
  'innecesarias. Cuanto más corta la respuesta, antes se puede reproducir ' +
  'en voz. Tu respuesta se va a leer en voz alta, así que evita listas, ' +
  'markdown o texto que no suene natural al hablarlo.';

// Raw RMS of the analyser's float waveform with the DC offset removed. The
// byte variant (getByteTimeDomainData) only has 1/128 resolution, so on a
// quiet mic it reads a flat ~0.005 whether or not anyone is talking — which
// is exactly why the call never saw speech start or stop. Floats keep the
// real (tiny) signal, and subtracting the mean stops a constant mic bias
// from looking like sound.
function readRms(analyser: AnalyserNode, buf: Float32Array<ArrayBuffer>): number {
  analyser.getFloatTimeDomainData(buf);
  let mean = 0;
  for (let i = 0; i < buf.length; i++) mean += buf[i];
  mean /= buf.length;
  let sum = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = buf[i] - mean;
    sum += v * v;
  }
  return Math.sqrt(sum / buf.length);
}

// Display level for the HUD core/bars: raw RMS is tiny on a quiet mic, so
// scale it up (clamped) so the visuals actually move.
const toDisplayLevel = (raw: number) => Math.min(1, raw * 12);

function isQuotaError(message: string | null | undefined): boolean {
  if (!message) return false;
  return /429|RESOURCE_EXHAUSTED|quota/i.test(message);
}

// Last-resort TTS when Gemini's free-tier quota (20 requests on the plan
// this was built against) is exhausted mid-call: the browser's own
// SpeechSynthesis is free, has no request limit, and keeps the call usable
// in a pinch — lower voice quality, but better than going silent entirely.
// Never used as the default path; only on a detected quota error.
function speakWithBrowserFallback(text: string): Promise<void> {
  return new Promise((resolve) => {
    if (!('speechSynthesis' in window)) {
      resolve();
      return;
    }
    const synth = window.speechSynthesis;
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = 'es-ES';

    const pickVoiceAndSpeak = () => {
      const voices = synth.getVoices();
      const esVoice = voices.find((v) => v.lang?.toLowerCase().startsWith('es'));
      if (esVoice) utter.voice = esVoice;
      utter.onend = () => resolve();
      utter.onerror = () => resolve();
      synth.speak(utter);
    };

    // If the voice list hasn't loaded yet, speak() can silently drop the
    // utterance — wait for it once, same as any other voices-changed gotcha.
    if (synth.getVoices().length > 0) {
      pickVoiceAndSpeak();
    } else {
      synth.onvoiceschanged = () => {
        synth.onvoiceschanged = null;
        pickVoiceAndSpeak();
      };
    }
  });
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
  // Manual override for recordTurn's current MediaRecorder — bound to the
  // Space key while a call is active, per the "if silence detection doesn't
  // fire, let me force it" fallback. Whatever was captured up to that point
  // is treated as a complete, valid utterance even if it never crossed the
  // speech threshold.
  const forceStopRef = useRef<(() => void) | null>(null);
  const lastPeakRef = useRef(0);
  const sendTurnRef = useRef(sendTurn);
  sendTurnRef.current = sendTurn;
  // Ambient noise floor measured fresh for each call (see calibrateNoiseFloor
  // in start()); thresholds below are derived from it instead of fixed
  // constants, so a noisier room or a hotter mic gain doesn't just silently
  // never trigger speech detection.
  const noiseFloorRef = useRef(0.001);
  const speechThreshold = useCallback(
    () => Math.max(MIN_SPEECH_RMS, noiseFloorRef.current * SPEECH_OVER_FLOOR),
    [],
  );
  const silenceThreshold = useCallback(
    () => Math.max(MIN_SILENCE_RMS, noiseFloorRef.current * SILENCE_OVER_FLOOR),
    [],
  );

  useEffect(() => {
    const Ctor = (window as any).MediaRecorder;
    if (!Ctor || !navigator.mediaDevices?.getUserMedia) {
      useCallStore.getState().setSupported(false);
    }
  }, []);

  // Manual fallback: press Space to force-send the current turn right now,
  // in case background noise keeps the silence detector from ever firing on
  // its own. Only active while a call is actually listening, and ignored
  // while typing in any text field elsewhere in the app.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || !activeRef.current || !forceStopRef.current) return;
      const target = e.target as HTMLElement | null;
      if (target && /^(input|textarea)$/i.test(target.tagName)) return;
      e.preventDefault();
      forceStopRef.current();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
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
    const data = new Float32Array(analyser.fftSize);

    const tick = () => {
      if (!activeRef.current || useTtsStore.getState().state !== 'speaking') {
        stopLevelLoop();
        useCallStore.getState().setLevel(0);
        source.disconnect();
        return;
      }
      useCallStore.getState().setLevel(toDisplayLevel(readRms(analyser, data)));
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
      const data = new Float32Array(analyser.fftSize);
      let speechFrames = 0;
      const tick = () => {
        if (settled || !activeRef.current) return;
        if (readRms(analyser, data) > speechThreshold()) {
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

      let peakLevel = 0;
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      let gotSpeech = false;
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };
      recorder.onstop = () => {
        lastPeakRef.current = peakLevel;
        stopLevelLoop();
        forceStopRef.current = null;
        resolve(
          gotSpeech && chunks.length
            ? new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
            : null,
        );
      };

      let hasSpoken = false;
      let silenceSince: number | null = null;
      const startedAt = Date.now();
      const data = new Float32Array(analyser.fftSize);
      const speechCutoff = speechThreshold();
      const silenceCutoff = silenceThreshold();
      let lastLevelLogAt = 0;
      console.log('[jarvis-call] recording turn — thresholds', {
        speech: speechCutoff.toFixed(5),
        floor: noiseFloorRef.current.toFixed(5),
        silence: silenceCutoff.toFixed(5),
      });

      const tick = () => {
        if (!activeRef.current) {
          if (recorder.state !== 'inactive') recorder.stop();
          return;
        }
        const level = readRms(analyser, data);
        if (level > peakLevel) peakLevel = level;
        useCallStore.getState().setLevel(toDisplayLevel(level));
        const now = Date.now();

        if (now - lastLevelLogAt > 500) {
          lastLevelLogAt = now;
          console.log('[jarvis-call] level', level.toFixed(5), 'peak', peakLevel.toFixed(5), hasSpoken ? '(speaking)' : '(waiting for speech)');
        }

        if (level > speechCutoff) {
          if (!hasSpoken) console.log('[jarvis-call] audio chunk captured — speech detected');
          hasSpoken = true;
          gotSpeech = true;
          silenceSince = null;
        } else if (
          hasSpoken &&
          level < Math.min(speechCutoff * 0.9, Math.max(silenceCutoff, peakLevel * SILENCE_PEAK_FRACTION))
        ) {
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
      forceStopRef.current = () => {
        console.log('[jarvis-call] forced send triggered via Space -> sending blob to Gemini STT');
        gotSpeech = true;
        if (recorder.state !== 'inactive') recorder.stop();
      };
      tick();
    });
  }, [stopLevelLoop, speechThreshold, silenceThreshold]);

  const loop = useCallback(async () => {
    while (activeRef.current) {
      console.log('[jarvis-call] listening...');
      useCallStore.getState().setState('listening');
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
        const msg = err instanceof Error ? err.message : '';
        useCallStore.getState().setError(
          isQuotaError(msg)
            ? 'Gemini free-tier quota exceeded — wait a bit before trying again'
            : msg
            ? `Transcription failed: ${msg}`
            : 'Transcription failed',
        );
        text = '';
      }
      if (!activeRef.current) break;
      if (!/\p{L}/u.test(text)) {
        // Empty or just "... ..." — Whisper's answer to silence/near-silence.
        if (lastPeakRef.current < 0.01) {
          useCallStore.getState().setError('Mic signal too weak — pick another microphone (mic icon) or raise the input volume in Windows');
        }
        continue;
      }
      useCallStore.getState().setError(null);

      let reply = '';
      try {
        reply = (await sendTurnRef.current(text)) ?? '';
        console.log('[jarvis-call] reply:', JSON.stringify(reply));
      } catch (err) {
        console.error('[jarvis-call] sendTurn failed', err);
        const msg = err instanceof Error ? err.message : '';
        useCallStore.getState().setError(
          isQuotaError(msg)
            ? 'Gemini free-tier quota exceeded — wait a bit before trying again'
            : msg
            ? `Request failed: ${msg}`
            : 'Request failed',
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
        if (isQuotaError(ttsAfterSpeak.error)) {
          console.log('[jarvis-call] Gemini TTS quota exhausted — falling back to browser speechSynthesis');
          useCallStore.getState().setError('Gemini voice quota exceeded — using browser voice for now');
          useCallStore.getState().setState('speaking');
          await speakWithBrowserFallback(reply);
          useCallStore.getState().setState('idle'); // re-enter loop -> back to 'listening'
          continue;
        }
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
      // (Reports of flat-zero levels turned out not to be caused by
      // noiseSuppression/autoGainControl — see the track/AudioContext
      // diagnostics logged right below instead.)
      const processing = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
      const wantedDevice = useAppStore.getState().settings.micDeviceId;
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: wantedDevice ? { ...processing, deviceId: { exact: wantedDevice } } : processing,
        });
      } catch (err) {
        // The saved device may be unplugged — fall back to the OS default
        // rather than failing the whole call.
        if (!wantedDevice || !(err instanceof DOMException) || err.name !== 'OverconstrainedError') throw err;
        console.warn('[jarvis-call] saved microphone unavailable, using default');
        stream = await navigator.mediaDevices.getUserMedia({ audio: processing });
      }
      console.log('[jarvis-call] microphone permission granted');
      for (const track of stream.getAudioTracks()) {
        // Flat-zero levels with no error anywhere usually trace back to one
        // of these: readyState !== 'live' (track already dead), enabled ===
        // false, or label pointing at the wrong input device entirely (e.g.
        // Windows handing the browser a silent "Stereo Mix"/virtual device
        // instead of the real mic).
        console.log('[jarvis-call] audio track:', {
          label: track.label,
          enabled: track.enabled,
          readyState: track.readyState,
          muted: track.muted,
          settings: track.getSettings(),
        });
        track.onmute = () => console.warn('[jarvis-call] track muted:', track.label);
        track.onunmute = () => console.log('[jarvis-call] track unmuted:', track.label);
        track.onended = () => console.error('[jarvis-call] track ended unexpectedly:', track.label);
      }
      streamRef.current = stream;
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      console.log('[jarvis-call] AudioContext state:', ctx.state, 'sampleRate:', ctx.sampleRate);
      if (ctx.state === 'suspended') {
        // Chrome/Edge can hand back a suspended context even right after a
        // click, if enough async work (the permission prompt) happened in
        // between and ate the "user gesture" window. A suspended context
        // still accepts node graph wiring without error, but every analyser
        // reads back silence — which looks exactly like "the mic isn't
        // picking up anything", with no exception anywhere to catch.
        await ctx.resume();
        // Read through an unknown cast — TS otherwise keeps `ctx.state`
        // narrowed to the literal 'suspended' from the check above across
        // the await, since it has no way to know resume() changes it.
        const stateAfterResume = ctx.state as unknown as AudioContextState;
        console.log('[jarvis-call] AudioContext resumed, state now:', stateAfterResume);
        if (stateAfterResume !== 'running') {
          console.error('[jarvis-call] AudioContext would not resume — mic analysis will not work');
          useCallStore.getState().setError('Audio engine blocked by the browser — click the core again');
        }
      }
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyserRef.current = analyser;

      // Calibrate the noise floor against this room/mic before judging any
      // real speech, so the speech/silence thresholds adapt instead of
      // relying on a constant tuned on someone else's machine.
      await new Promise<void>((resolve) => {
        const data = new Float32Array(analyser.fftSize);
        const samples: number[] = [];
        const startedAt = performance.now();
        const sample = () => {
          const elapsed = performance.now() - startedAt;
          const level = readRms(analyser, data);
          if (elapsed >= NOISE_FLOOR_WARMUP_MS) samples.push(level);
          if (elapsed < NOISE_FLOOR_WARMUP_MS + NOISE_FLOOR_CALIBRATION_MS) {
            requestAnimationFrame(sample);
          } else {
            const avg = samples.reduce((a, b) => a + b, 0) / Math.max(1, samples.length);
            noiseFloorRef.current = avg;
            console.log('[jarvis-call] noise floor calibrated:', avg.toFixed(5), '(stay quiet during this ~1s)');
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
    forceStopRef.current = null;
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
