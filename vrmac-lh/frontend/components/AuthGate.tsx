"use client";
import { FormEvent, useEffect, useState } from "react";
import { ApiError, login, logout, me, User } from "@/lib/api";
import { useT } from "@/lib/i18n";

const SAMPLE: Record<string, string> = {
  host: "host1@example.org",
  ambassador: "ambassador1@example.org",
  validator: "validator1@example.org",
  institution: "institution1@example.org",
};

interface Props {
  roles: User["role"][];
  children: (user: User, signOut: () => void) => React.ReactNode;
}

/** Renders a login form until a user with one of the required roles is signed in. */
export default function AuthGate({ roles, children }: Props) {
  const t = useT();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState(SAMPLE[roles[0]] ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    me().then((u) => {
      setUser(u);
      setLoading(false);
    });
  }, []);

  const signOut = () => {
    logout();
    setUser(null);
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await login(email, password);
      setUser(r.user);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? t("auth.failed") : t("common.error", { message: String(err) }));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p aria-live="polite">{t("common.loading")}</p>;

  if (user && !roles.includes(user.role)) {
    return (
      <div className="alert alert-warn" role="alert">
        <p>{t("auth.wrongRole", { role: user.role, roles: roles.join(", ") })}</p>
        <button type="button" className="btn btn-secondary" onClick={signOut}>
          {t("auth.logout")}
        </button>
      </div>
    );
  }

  if (user) return <>{children(user, signOut)}</>;

  return (
    <form className="card login" onSubmit={submit} aria-describedby="login-help">
      <h2>{t("auth.login")}</h2>
      <p id="login-help">{t("auth.required")}</p>
      <label className="field">
        <span>{t("auth.email")}</span>
        <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </label>
      <label className="field">
        <span>{t("auth.password")}</span>
        <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </label>
      {error && (
        <p className="alert alert-danger" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="btn btn-primary" disabled={busy}>
        {t("auth.login")}
      </button>
      <p className="muted small">
        {t("auth.sample", { password: "prototype123", accounts: roles.map((r) => SAMPLE[r]).join(", ") })}
      </p>
    </form>
  );
}
