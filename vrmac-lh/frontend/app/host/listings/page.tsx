"use client";
/** "My listings": every listing of the signed-in host, in every status, with the edit form. */
import HostShell from "@/components/host/HostShell";
import MyListings from "@/components/host/MyListings";

export default function MyListingsPage() {
  return <HostShell>{() => <MyListings />}</HostShell>;
}
