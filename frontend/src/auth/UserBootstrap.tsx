import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { useUserStore } from "./userStore";

export function UserBootstrap({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const users = await api.listUsers();
        if (cancelled) return;
        const cur = useUserStore.getState().userId;
        if (users.length > 0 && (cur == null || !users.some((u) => u.id === cur))) {
          useUserStore.getState().setUserId(users[0].id);
        }
      } catch {
        /* API down — still render; requests fall back to default user on server */
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return (
      <div className="h-full flex items-center justify-center text-slate-500 text-sm bg-slate-50">
        Loading…
      </div>
    );
  }
  return <>{children}</>;
}
