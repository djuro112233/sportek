/**
 * Browser audio helpers: a MediaRecorder wrapper (press to start, press to stop) and a small
 * player for WAV blobs / URLs. No audio is kept after upload; blobs are released on stop.
 */

export const PREFERRED_MIME_TYPES: readonly string[] = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/mp4',
];

/** Hard cap on one recording; the UI auto-stops at this point. */
export const MAX_RECORDING_MS = 60_000;

export type RecorderErrorKind = 'unsupported' | 'denied' | 'failed';

export class RecorderError extends Error {
  readonly kind: RecorderErrorKind;
  constructor(kind: RecorderErrorKind, message: string) {
    super(message);
    this.name = 'RecorderError';
    this.kind = kind;
  }
}

type MediaRecorderCtor = typeof MediaRecorder;

function mediaRecorderCtor(): MediaRecorderCtor | null {
  const g = globalThis as { MediaRecorder?: MediaRecorderCtor };
  return typeof g.MediaRecorder === 'function' ? g.MediaRecorder : null;
}

export function isRecordingSupported(): boolean {
  if (!mediaRecorderCtor()) return false;
  const nav = (globalThis as { navigator?: Navigator }).navigator;
  return Boolean(nav && nav.mediaDevices && typeof nav.mediaDevices.getUserMedia === 'function');
}

/** First supported MIME type from the preference list, or undefined for the browser default. */
export function pickMimeType(): string | undefined {
  const ctor = mediaRecorderCtor();
  if (!ctor || typeof ctor.isTypeSupported !== 'function') return undefined;
  for (const mime of PREFERRED_MIME_TYPES) {
    try {
      if (ctor.isTypeSupported(mime)) return mime;
    } catch {
      // some WebViews throw on unknown types; keep looking
    }
  }
  return undefined;
}

export function extensionFor(mime: string | undefined): string {
  const base = (mime ?? '').split(';')[0].trim().toLowerCase();
  switch (base) {
    case 'audio/webm':
      return 'webm';
    case 'audio/ogg':
      return 'ogg';
    case 'audio/mp4':
      return 'm4a';
    case 'audio/wav':
    case 'audio/x-wav':
      return 'wav';
    case 'audio/mpeg':
      return 'mp3';
    default:
      return 'bin';
  }
}

export function formatSeconds(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r < 10 ? '0' : ''}${r}`;
}

export interface Recording {
  blob: Blob;
  mimeType: string;
  fileName: string;
  durationMs: number;
}

export class Recorder {
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private chunks: Blob[] = [];
  private startedAt = 0;
  private maxTimer: ReturnType<typeof setTimeout> | null = null;
  private stopResolvers: Array<(r: Recording) => void> = [];
  private stopRejecters: Array<(e: Error) => void> = [];
  private autoStopHandler: (() => void) | null = null;

  get recording(): boolean {
    return this.recorder !== null && this.recorder.state === 'recording';
  }

  /** Request the microphone and start recording. Rejects with RecorderError. */
  async start(onAutoStop?: () => void): Promise<void> {
    if (this.recording) return;
    const ctor = mediaRecorderCtor();
    if (!ctor || !isRecordingSupported()) {
      throw new RecorderError('unsupported', 'MediaRecorder is not available');
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch (err) {
      const name = err instanceof Error ? err.name : '';
      if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') {
        throw new RecorderError('denied', 'microphone permission denied');
      }
      if (name === 'NotFoundError' || name === 'NotSupportedError' || name === 'OverconstrainedError') {
        throw new RecorderError('unsupported', 'no usable microphone');
      }
      throw new RecorderError('failed', name || 'getUserMedia failed');
    }

    let recorder: MediaRecorder;
    const mime = pickMimeType();
    try {
      recorder = mime ? new ctor(stream, { mimeType: mime }) : new ctor(stream);
    } catch {
      try {
        recorder = new ctor(stream); // fall back to the browser default container
      } catch (err) {
        stream.getTracks().forEach((t) => t.stop());
        throw new RecorderError('failed', err instanceof Error ? err.message : 'MediaRecorder failed');
      }
    }

    this.stream = stream;
    this.recorder = recorder;
    this.chunks = [];
    this.autoStopHandler = onAutoStop ?? null;

    recorder.ondataavailable = (ev: BlobEvent) => {
      if (ev.data && ev.data.size > 0) this.chunks.push(ev.data);
    };
    recorder.onerror = () => {
      const err = new RecorderError('failed', 'recording error');
      this.finish(null, err);
    };
    recorder.onstop = () => {
      const type = recorder.mimeType || mime || 'application/octet-stream';
      const blob = new Blob(this.chunks, { type });
      const durationMs = Date.now() - this.startedAt;
      this.finish({ blob, mimeType: type, fileName: `question.${extensionFor(type)}`, durationMs }, null);
    };

    this.startedAt = Date.now();
    try {
      recorder.start(500); // timeslice keeps memory bounded on long recordings
    } catch (err) {
      this.releaseStream();
      this.recorder = null;
      throw new RecorderError('failed', err instanceof Error ? err.message : 'start failed');
    }
    this.maxTimer = setTimeout(() => {
      if (this.recording) {
        this.autoStopHandler?.();
        void this.stop().catch(() => undefined);
      }
    }, MAX_RECORDING_MS);
  }

  /** Stop and resolve with the recorded blob. */
  stop(): Promise<Recording> {
    const rec = this.recorder;
    if (!rec || rec.state === 'inactive') {
      return Promise.reject(new RecorderError('failed', 'not recording'));
    }
    return new Promise<Recording>((resolve, reject) => {
      this.stopResolvers.push(resolve);
      this.stopRejecters.push(reject);
      try {
        rec.stop();
      } catch (err) {
        this.finish(null, new RecorderError('failed', err instanceof Error ? err.message : 'stop failed'));
      }
    });
  }

  /** Discard the current recording without producing a blob. */
  cancel(): void {
    const rec = this.recorder;
    this.stopResolvers = [];
    this.stopRejecters = [];
    if (rec && rec.state !== 'inactive') {
      rec.onstop = null;
      rec.ondataavailable = null;
      try {
        rec.stop();
      } catch {
        // already stopped
      }
    }
    this.chunks = [];
    this.recorder = null;
    this.clearMaxTimer();
    this.releaseStream();
  }

  private finish(result: Recording | null, error: Error | null): void {
    const resolvers = this.stopResolvers;
    const rejecters = this.stopRejecters;
    this.stopResolvers = [];
    this.stopRejecters = [];
    this.chunks = [];
    this.recorder = null;
    this.clearMaxTimer();
    this.releaseStream();
    if (result) resolvers.forEach((r) => r(result));
    else rejecters.forEach((r) => r(error ?? new RecorderError('failed', 'recording failed')));
  }

  private clearMaxTimer(): void {
    if (this.maxTimer) {
      clearTimeout(this.maxTimer);
      this.maxTimer = null;
    }
  }

  private releaseStream(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }
}

export type PlayerState = 'idle' | 'loading' | 'playing';

/** Minimal audio player; one sound at a time; releases object URLs. */
export class Player {
  private audio: HTMLAudioElement | null = null;
  private objectUrl: string | null = null;
  private listeners = new Set<(s: PlayerState) => void>();
  private state: PlayerState = 'idle';

  subscribe(fn: (s: PlayerState) => void): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  get current(): PlayerState {
    return this.state;
  }

  private setState(s: PlayerState): void {
    this.state = s;
    this.listeners.forEach((fn) => fn(s));
  }

  async play(source: Blob | string): Promise<void> {
    this.stop();
    if (typeof Audio === 'undefined') throw new Error('audio not supported');
    const audio = new Audio();
    audio.preload = 'auto';
    this.audio = audio;
    if (typeof source === 'string') {
      audio.src = source;
    } else {
      this.objectUrl = URL.createObjectURL(source);
      audio.src = this.objectUrl;
    }
    audio.onended = () => this.cleanup(audio);
    audio.onerror = () => this.cleanup(audio);
    this.setState('loading');
    try {
      await audio.play();
      if (this.audio === audio) this.setState('playing');
    } catch (err) {
      this.cleanup(audio);
      throw err;
    }
  }

  stop(): void {
    const audio = this.audio;
    if (audio) this.cleanup(audio);
  }

  private cleanup(audio: HTMLAudioElement): void {
    if (this.audio !== audio) return;
    try {
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
    } catch {
      // element already released
    }
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
    this.audio = null;
    this.setState('idle');
  }
}
