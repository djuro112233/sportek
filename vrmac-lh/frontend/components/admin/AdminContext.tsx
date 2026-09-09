"use client";
import { createContext, useContext } from "react";
import type { User } from "@/lib/api";

interface AdminCtx {
  user: User;
  signOut: () => void;
}

const Ctx = createContext<AdminCtx | null>(null);

export function AdminProvider({ user, signOut, children }: AdminCtx & { children: React.ReactNode }) {
  return <Ctx.Provider value={{ user, signOut }}>{children}</Ctx.Provider>;
}

/** The signed-in admin user (validator / ambassador / institution) provided by the section layout. */
export function useAdminUser(): AdminCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAdminUser must be used inside <AdminProvider>");
  return v;
}
