/**
 * Visitor-side calls. Every endpoint here is public: `auth: false`, no token is ever attached.
 * Paths and payloads follow `docs/api-contract.md` exactly.
 */
import { api } from "@/lib/api";
import { deviceId } from "./device";
import type {
  AskResponse,
  CalendarEntry,
  HeritageEntry,
  ItineraryRequest,
  ItineraryResponse,
  Listing,
  MapFeatureCollection,
  Trail,
  TrailReportAccepted,
  TrailReportIn,
  Village,
  VisitEventIn,
  VisitorRequest,
  VisitorRequestIn,
} from "./types";

const PUBLIC = { auth: false as const };

export function getMapFeatures(): Promise<MapFeatureCollection> {
  return api<MapFeatureCollection>("/api/map/features", PUBLIC);
}

export function getVillages(municipality?: string): Promise<Village[]> {
  const q = municipality ? `?municipality=${encodeURIComponent(municipality)}` : "";
  return api<Village[]>(`/api/villages${q}`, PUBLIC);
}

export function getHeritageEntry(slugOrId: string): Promise<HeritageEntry> {
  return api<HeritageEntry>(`/api/heritage/${encodeURIComponent(slugOrId)}`, PUBLIC);
}

export function getCalendar(): Promise<CalendarEntry[]> {
  return api<CalendarEntry[]>("/api/heritage/calendar", PUBLIC);
}

export function getListing(slugOrId: string): Promise<Listing> {
  return api<Listing>(`/api/listings/${encodeURIComponent(slugOrId)}`, PUBLIC);
}

export function getTrails(): Promise<Trail[]> {
  return api<Trail[]>("/api/trails", PUBLIC);
}

export function getTrail(slugOrId: string): Promise<Trail> {
  return api<Trail>(`/api/trails/${encodeURIComponent(slugOrId)}`, PUBLIC);
}

/** GPX is `application/gpx+xml`; `api()` hands back the raw text when the body is not JSON. */
export function getTrailGpx(slugOrId: string): Promise<string> {
  return api<string>(`/api/trails/${encodeURIComponent(slugOrId)}/gpx`, PUBLIC);
}

/** 202 — the report is stored as a draft and becomes visible only after validation. */
export function postTrailReport(trailId: string, body: TrailReportIn): Promise<TrailReportAccepted> {
  return api<TrailReportAccepted>(`/api/trails/${encodeURIComponent(trailId)}/reports`, {
    ...PUBLIC,
    method: "POST",
    body: { ...body, device_id: body.device_id ?? deviceId() },
  });
}

export function postAsk(body: { question: string; lang: string; session_id: string; device_id: string }): Promise<AskResponse> {
  return api<AskResponse>("/api/ask", { ...PUBLIC, method: "POST", body });
}

export function postItinerary(body: ItineraryRequest): Promise<ItineraryResponse> {
  return api<ItineraryResponse>("/api/itinerary", { ...PUBLIC, method: "POST", body });
}

export function postRequest(body: VisitorRequestIn): Promise<VisitorRequest> {
  return api<VisitorRequest>("/api/requests", {
    ...PUBLIC,
    method: "POST",
    body: { ...body, device_id: body.device_id ?? deviceId() },
  });
}

export function getMyRequests(sessionId: string): Promise<VisitorRequest[]> {
  return api<VisitorRequest[]>(`/api/requests/mine?session_id=${encodeURIComponent(sessionId)}`, PUBLIC);
}

export function cancelRequest(id: string, sessionId: string): Promise<VisitorRequest> {
  return api<VisitorRequest>(`/api/requests/${encodeURIComponent(id)}/cancel`, {
    ...PUBLIC,
    method: "POST",
    body: { session_id: sessionId },
  });
}

/** "I'm here": one anonymous, pseudonymised event. Never shown per person, only aggregated (k≥5). */
export function postVisit(body: VisitEventIn): Promise<unknown> {
  return api<unknown>("/api/events", { ...PUBLIC, method: "POST", body });
}

/** Message of a failed call, without leaking a stack trace into the UI. */
export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  if (typeof e === "string") return e;
  return "unknown error";
}
