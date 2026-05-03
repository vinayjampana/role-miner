import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { LoginPage } from "./LoginPage";
import { authFetch, useUserStore } from "./userStore";

export function UserBootstrap({ children }: { children: ReactNode }) {
  const token = useUserStore((s) => s.token);
  const [phase, setPhase] = useState<"loading" | "login" | "app">("loading");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await useUserStore.persist.rehydrate();
      if (cancelled) return;
      const t = useUserStore.getState().token;
      if (!t) {
        const probe = await authFetch("/api/jobs/latest?min_score=6");
        if (cancelled) return;
        if (probe.status === 401) {
          setPhase("login");
          return;
        }
        setPhase("app");
        return;
      }
      try {
        await api.auth.me();
        if (!cancelled) setPhase("app");
      } catch {
        useUserStore.getState().logout();
        if (!cancelled) setPhase("login");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (phase === "loading") {
    return (
      <div className="h-full flex items-center justify-center text-slate-500 text-sm bg-slate-50">
        Loading…
      </div>
    );
  }
  if (phase === "login") {
    return <LoginPage />;
  }
  return <>{children}</>;
}
