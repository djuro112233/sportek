# MILA web client

Mobile-first, voice-first UI for the MILA backend. One screen: consent, a big microphone
button, a text box, and the answer with tappable citations and a referral card.
Information + referral only; it never diagnoses, doses or interprets results.

Built with Next.js 14 (app router) and TypeScript. No UI framework, no web fonts, no images,
no analytics, no login. The only runtime dependencies are `next`, `react` and `react-dom`.

## Run

```bash
cd web
cp .env.example .env.local        # MILA_API_URL if the API is not on localhost:8000
npm ci
npm run dev                       # http://localhost:3000
```

The browser only ever talks to the web origin: every call goes to `/api/...` on the same host
and `app/api/[...path]/route.ts` forwards it to the API. No CORS setup is needed for this
default. Microphone access needs a secure context: `localhost` works, a phone on the LAN needs
HTTPS (or Chrome's `chrome://flags/#unsafely-treat-insecure-origin-as-secure` for testing).

## Reaching the API

| Variable | When it is read | Meaning |
|---|---|---|
| `MILA_API_URL` | at runtime, by the Next.js server | Where `/api/*` is forwarded. Default `http://localhost:8000`; `docker-compose.yml` sets `http://api:8000`. Change it and restart, no rebuild. |
| `NEXT_PUBLIC_API_BASE` | at build time, inlined into the bundle | Optional override for static deployments: when non-empty the browser calls that origin directly and skips the proxy. The API must then list the web origin in `MILA_CORS_ORIGINS` and expose `Retry-After`. Leave empty otherwise. |

The proxy (`lib/proxy.ts`) forwards `GET`, `POST` and `DELETE`, streams request bodies (audio
uploads are not buffered), passes only `Content-Type`, `X-Admin-Token` and `Accept` upstream,
and returns the status plus `Content-Type`, `Content-Disposition`, `Cache-Control` and
`Retry-After`. Nothing is cached (`dynamic = 'force-dynamic'`, `Cache-Control: no-store`),
cookies never exist on either side, and an unreachable API answers `502`/`504` JSON. The
route handler is part of the standalone output, so the Docker image needs no rebuild to point
at another API.

## Checks

```bash
npm run lint        # eslint (next/core-web-vitals)
npm run typecheck   # tsc --noEmit
npm test            # node:test, needs Node 22.18+ (runs .ts directly); the app itself runs on Node 20+
npm run build       # production build, standalone output
```

CI (`.github/workflows/ci.yml`, job `web`) runs all four on Node 22 and builds the Docker image
without pushing it.

## Docker

```bash
docker build -t mila-web .
docker run --rm -p 3000:3000 -e MILA_API_URL=http://host.docker.internal:8000 mila-web
```

Multi-stage `node:20-alpine` image, non-root user, Next.js standalone server on port 3000.
`MILA_API_URL` is a runtime environment variable of the container (default
`http://localhost:8000`). `--build-arg NEXT_PUBLIC_API_BASE=https://api.example.org` bakes a
direct API origin into the bundle instead (see the table above); the compose file does not use
it. Next.js build telemetry is disabled in the image (`NEXT_TELEMETRY_DISABLED=1`); set the
same variable locally if you prefer.

## Layout

| Path | Purpose |
|---|---|
| `app/page.tsx` | The single screen and its state machine (consent, ready, recording, transcribing, confirm, asking) |
| `app/api/[...path]/route.ts` | Runtime proxy `/api/*` -> `MILA_API_URL` (see `lib/proxy.ts`) |
| `app/layout.tsx`, `app/globals.css` | Document shell, CSS variables, 18px base font, 48px tap targets, reduced-motion rules |
| `components/ConsentDialog.tsx` | Language, under-18, region, consent text with Listen, "save my questions" (off by default), I agree; reloads the text on `409 consent_version_outdated` |
| `components/MicButton.tsx` | Press to record, press again to stop; recording state and timer |
| `components/TranscriptConfirm.tsx` | "I heard: … Is this right?" with Yes / No / Edit |
| `components/AnswerView.tsx` | Sentences one per line with `[S1]` chips, confidence in words, translated note, demo badge, minor note, Listen, disclaimer, referral |
| `components/CitationSheet.tsx` | Bottom sheet (native `<dialog>`, modal) with source title, section, version, date, page, review status |
| `components/ReferralCard.tsx` | Referral points with `tel:` call buttons and a "not yet verified" label |
| `components/EmergencyCard.tsx` | Red-flag outcome: emergency card with Listen, the message once, referral first, no answer text |
| `components/Footer.tsx` | Language switch, low-data mode, delete my data, long disclaimer |
| `lib/api.ts` | Typed client with AbortController timeouts (`GET /api/health`, `GET /api/consent/text`, `POST /api/consent`, `GET /api/session/{id}`, `POST /api/session/{id}/preferences`, `DELETE /api/session/{id}`, `POST /api/transcribe`, `POST /api/speak`, `POST /api/ask`, `GET` of `audio_url`), `Retry-After` parsing |
| `lib/proxy.ts` | The forwarding logic behind the route handler (unit-tested without a server) |
| `lib/types.ts` | Request and response types mirroring `backend/app/core/types.py` (including `gate` and `minor_note`) |
| `lib/voice.ts` | MediaRecorder wrapper (`audio/webm;codecs=opus` with fallback) and a small audio player |
| `lib/storage.ts` | Safe storage wrappers: session in `sessionStorage`, preferences in `localStorage` |
| `lib/i18n.ts` | UI strings for sr, bs, me, hr, en; Serbian Cyrillic is generated by transliteration (digraphs first), mirroring the backend |
| `tests/` | `node:test` suites for i18n, storage, the API client and the proxy |

## Behaviour notes

- Voice: press the mic to record, press again to stop (auto-stop at 60 s). The recording is
  uploaded to `/api/transcribe` and shown back as "I heard: …" before anything is asked. The
  browser blob is released right after upload. If `MediaRecorder` is missing the mic is hidden
  and typing still works.
- Audio: answers to voice questions play automatically unless low-data mode is on. The server's
  `audio_url` is served exactly once, so the client fetches it into a Blob first and plays from
  memory; a refused autoplay (iOS) or a later Listen replays the same Blob and the token is
  never requested twice. If that fetch fails (expired token, network) Listen falls back to
  `POST /api/speak` with the answer text and the `low_bandwidth` flag (8 kHz on the server).
  The emergency card has the same Listen / Stop control under its title.
- Low-data mode is remembered on the device. It turns off automatic playback and requests
  small audio.
- Outcomes: `answered` shows sentences with citation chips; `withheld` shows "I don't know
  this" plus the referral card; `redflag` shows a high-visibility emergency card with call
  buttons first and no answer text. When the gate reports `pipeline_error` (an infrastructure
  failure, not a knowledge gap) the client shows the server-error state with Try again and
  keeps the question in the box instead of an answer.
- Minors: when the session is for someone under 18 the server adds `minor_note` ("you can also
  talk to a trusted adult"); it is shown under the answer, the withheld text and the red-flag
  message.
- Referral points show name, kind, address, hours, a call button (only when a phone number
  exists) and a website link. Every non-emergency point without a `verified_on` date carries a
  localised "not yet verified" label. Internal notes are not part of the API and are never shown.
- Rate limit: a `429` is shown as "too many questions" and Try again stays disabled for the
  `Retry-After` seconds (countdown on the button; 60 s when the header is missing).
- Delete my data calls `DELETE /api/session/{id}` and then clears both storages. If the server
  cannot be reached the user can retry or clear only this phone.
- Every request has a timeout (12 s for small calls, 45 s transcribe, 30 s speak, 60 s ask) and
  a clear retry control.
- Session validity: at start the client asks `GET /api/session/{id}`; `{exists: false}` or
  `consent_given: false` forgets the session and shows the consent screen with "your session
  has ended". A `403` from any later call (unknown session, consent missing, or
  `consent_version_outdated` after the server's consent text changed) does the same; network
  errors keep the stored session. A `409 consent_version_outdated` while agreeing reloads the
  consent text and says that it changed.
- Storage: the session id with the language, script, region and under-18 flag fixed at consent
  live in `sessionStorage` (this tab only, gone when the browser closes), so a shared clinic
  phone never resumes someone else's session without a new consent. Only non-identifying
  preferences (language, script, low-data mode) are kept in `localStorage`. The client sends a
  changed language or script to `POST /api/session/{id}/preferences` (region and the under-18
  flag are set at consent).
- The transcript's `confidence` is received but not yet used: every transcript is shown for
  confirmation the same way.

## Accessibility

18px base font, 48px minimum tap targets, visible focus rings, AA colour contrast (control
borders at 4.8:1 on white, decorative lines lighter), one `h1` per page (the MILA brand), `aria-live`
regions for the recording state and the answer, `role="alert"` for errors and the emergency
card, the citation sheet is a native modal `<dialog>` (focus trapped, Escape and backdrop close
it, focus returns to the chip), and `prefers-reduced-motion` disables the pulse and scroll
animations.
