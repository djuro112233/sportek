"use client";
/**
 * A new listing: the voice-first onboarding wizard inside the host frame.
 *
 * `HostShell` supplies the login gate (roles `host` and `ambassador`), the service worker and the
 * offline capture queue; the wizard itself carries the seven steps and the active-time clock.
 */
import HostShell from "@/components/host/HostShell";
import Wizard from "@/components/host/Wizard";

export default function NewListingPage() {
  return <HostShell>{(user) => <Wizard user={user} />}</HostShell>;
}
