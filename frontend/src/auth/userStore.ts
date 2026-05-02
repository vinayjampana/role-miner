import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UserState {
  userId: number | null;
  setUserId: (id: number | null) => void;
}

export const useUserStore = create<UserState>()(
  persist(
    (set) => ({
      userId: null,
      setUserId: (id) => set({ userId: id }),
    }),
    { name: "roleminer-active-user" }
  )
);

export function authHeaders(): HeadersInit {
  const id = useUserStore.getState().userId;
  const h: Record<string, string> = {};
  if (id != null && id > 0) h["X-User-Id"] = String(id);
  return h;
}

export async function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  const ah = authHeaders() as Record<string, string>;
  for (const [k, v] of Object.entries(ah)) headers.set(k, v);
  return fetch(input, { ...init, headers });
}

export function streamUserQuery(): string {
  const id = useUserStore.getState().userId;
  const uid = id != null && id > 0 ? id : 1;
  return `user_id=${uid}`;
}
