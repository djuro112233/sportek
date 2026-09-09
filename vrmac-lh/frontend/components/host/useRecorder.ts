"use client";
/**
 * Browser audio capture for the wizard.
 *
 * `audio/webm;codecs=opus` first, with fallbacks for browsers that cannot produce it; the
 * microphone is released as soon as the recording stops. When the browser has no MediaRecorder, or
 * the host refuses the microphone, the wizard offers the two alternatives instead (upload a file,
 * or type the description).
 */
import { useCallback, useEffect, useRef, useState } from "react";

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/ogg",
  "audio/mp4",
  "audio/mpeg",
];

export type RecorderState = "unsupported" | "idle" | "requesting" | "recording" | "recorded" | "denied" | "error";

export interface Recording {
  blob: Blob;
  url: string;
  durationSeconds: number;
  capturedAt: string;
  mime: string;
}

export interface RecorderApi {
  state: RecorderState;
  supported: boolean;
  seconds: number;
  recording: Recording | null;
  errorMessage: string;
  start: () => Promise<void>;
  stop: () => void;
  reset: () => void;
  /** Adopt an uploaded file as if it had been recorded here. */
  adopt: (file: File) => void;
}

export function recorderSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof MediaRecorder !== "undefined" &&
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia)
  );
}

function pickMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const m of MIME_CANDIDATES) {
    try {
      if (MediaRecorder.isTypeSupported(m)) return m;
    } catch {
      /* older implementations throw on unknown types */
    }
  }
  return "";
}

export function useRecorder(): RecorderApi {
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<BlobPart[]>([]);
  const stream = useRef<MediaStream | null>(null);
  const startedAt = useRef<number>(0);
  const capturedAt = useRef<string>("");
  const tick = useRef<number | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    setState(recorderSupported() ? "idle" : "unsupported");
  }, []);

  const stopTicking = useCallback(() => {
    if (tick.current !== null) {
      window.clearInterval(tick.current);
      tick.current = null;
    }
  }, []);

  const releaseStream = useCallback(() => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  }, []);

  const revoke = useCallback(() => {
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  useEffect(
    () => () => {
      stopTicking();
      releaseStream();
      revoke();
    },
    [stopTicking, releaseStream, revoke],
  );

  const start = useCallback(async () => {
    if (!recorderSupported()) {
      setState("unsupported");
      return;
    }
    setErrorMessage("");
    setState("requesting");
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.current = media;
      const mime = pickMime();
      const rec = mime ? new MediaRecorder(media, { mimeType: mime }) : new MediaRecorder(media);
      recorder.current = rec;
      chunks.current = [];
      rec.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunks.current.push(e.data);
      };
      rec.onerror = () => {
        setState("error");
        setErrorMessage("recorder");
        stopTicking();
        releaseStream();
      };
      rec.onstop = () => {
        stopTicking();
        releaseStream();
        const type = rec.mimeType || mime || "audio/webm";
        const blob = new Blob(chunks.current, { type });
        chunks.current = [];
        revoke();
        if (blob.size === 0) {
          setState("idle");
          return;
        }
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        setRecording({
          blob,
          url,
          durationSeconds: Math.max(1, Math.round((Date.now() - startedAt.current) / 1000)),
          capturedAt: capturedAt.current,
          mime: type,
        });
        setState("recorded");
      };
      revoke();
      setRecording(null);
      startedAt.current = Date.now();
      capturedAt.current = new Date().toISOString();
      setSeconds(0);
      rec.start(1000); // a timeslice keeps data available even if the tab is closed abruptly
      setState("recording");
      tick.current = window.setInterval(() => {
        setSeconds(Math.round((Date.now() - startedAt.current) / 1000));
      }, 500);
    } catch (e) {
      releaseStream();
      const name = e instanceof DOMException ? e.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") {
        setState("denied");
      } else {
        setState("error");
        setErrorMessage(e instanceof Error ? e.message : String(e));
      }
    }
  }, [releaseStream, revoke, stopTicking]);

  const stop = useCallback(() => {
    const rec = recorder.current;
    if (rec && rec.state !== "inactive") rec.stop();
    else {
      stopTicking();
      releaseStream();
    }
  }, [releaseStream, stopTicking]);

  const reset = useCallback(() => {
    revoke();
    setRecording(null);
    setSeconds(0);
    setErrorMessage("");
    setState(recorderSupported() ? "idle" : "unsupported");
  }, [revoke]);

  const adopt = useCallback(
    (file: File) => {
      revoke();
      const url = URL.createObjectURL(file);
      urlRef.current = url;
      setRecording({
        blob: file,
        url,
        durationSeconds: 0,
        capturedAt: new Date(file.lastModified || Date.now()).toISOString(),
        mime: file.type || "audio/webm",
      });
      setSeconds(0);
      setState("recorded");
    },
    [revoke],
  );

  return { state, supported: state !== "unsupported", seconds, recording, errorMessage, start, stop, reset, adopt };
}
