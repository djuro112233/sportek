/**
 * Anonymous client ids for the visitor app.
 *
 * `session_id` comes from `lib/api.ts` (`sessionId()`); the contract also allows a `device_id`, so we
 * generate one **here** rather than in the shared module.
 *
 * What this is: a random value (crypto UUID) written once to `localStorage` and sent with the calls
 * the contract allows (`/api/ask`, `/api/events`, `/api/itinerary`, `/api/requests`,
 * `/api/trails/{id}/reports`). What it is not: it is **not** a fingerprint — nothing about the
 * browser, the screen, the fonts or the network is read; the value is not derived from anything.
 * It carries no name, no e-mail, no IP address. The server never stores it in the clear: it is
 * pseudonymised (keyed HMAC, `app/pseudonym.py`) before it reaches the event stream, and events are
 * only ever shown aggregated with k≥5. Clearing the browser storage erases it for good.
 */

const DEVICE_KEY = "vrmac.device";

function randomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `d-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
}

/** The anonymous device id of this browser, created on first use. */
export function deviceId(): string {
  try {
    let id = localStorage.getItem(DEVICE_KEY);
    if (!id) {
      id = randomId();
      localStorage.setItem(DEVICE_KEY, id);
    }
    return id;
  } catch {
    // Private mode / storage disabled: stay anonymous for this page load only.
    return "d-ephemeral";
  }
}

/** Forget the anonymous ids stored in this browser. */
export function forgetDeviceId(): void {
  try {
    localStorage.removeItem(DEVICE_KEY);
  } catch {
    /* ignore */
  }
}
