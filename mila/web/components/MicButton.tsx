'use client';

import { formatSeconds } from '@/lib/voice';

export type MicState = 'idle' | 'recording' | 'busy';

interface Props {
  state: MicState;
  disabled?: boolean;
  seconds?: number;
  labels: { start: string; stop: string; recording: string };
  onPress: () => void;
}

function MicIcon() {
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect x="25" y="10" width="14" height="26" rx="7" fill="currentColor" />
      <path d="M18 30a14 14 0 0 0 28 0" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" />
      <path d="M32 44v8M24 52h16" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect x="18" y="18" width="28" height="28" rx="5" fill="currentColor" />
    </svg>
  );
}

/** Big round press-to-record button. Press once to start, press again to stop. */
export default function MicButton({ state, disabled, seconds, labels, onPress }: Props) {
  const recording = state === 'recording';
  const busy = state === 'busy';
  const label = recording ? labels.stop : labels.start;
  const className = ['mic', recording ? 'mic--recording' : '', busy ? 'mic--busy' : ''].filter(Boolean).join(' ');

  return (
    <div className="mic-wrap">
      <button
        type="button"
        className={className}
        aria-pressed={recording}
        aria-label={label}
        aria-describedby="mic-state"
        disabled={disabled || busy}
        onClick={onPress}
      >
        {recording ? <StopIcon /> : <MicIcon />}
      </button>
      <div id="mic-state" className={recording ? 'mic-label mic-label--recording' : 'mic-label'}>
        {recording ? labels.recording : labels.start}
      </div>
      {recording ? (
        <div className="mic-timer" aria-hidden="true">
          {formatSeconds(seconds ?? 0)}
        </div>
      ) : null}
    </div>
  );
}
