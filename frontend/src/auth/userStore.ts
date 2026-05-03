import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UserState {
  userId: number | null;
  token: string | null;
  name: string | null;
  email: string | null;
  setUserId: (id: number | null) => void;
  setAuth: (token: string, userId: number, name: string, email: string | null) => void;
  logout: () => void;
}

export const useUserStore = create<UserState>()(
  persist(
    (set) => ({
      userId: null,
      token: null,
      name: null,
      email: null,
      setUserId: (id) => set({ userId: id }),
      setAuth: (token, userId, name, email) => set({ token, userId, name, email }),
      logout: () => set({ token: null, userId: null, name: null, email: null }),
    }),
    {
      name: "roleminer-active-user",
      partialize: (s) => ({
        userId: s.userId,
        token: s.token,
        name: s.name,
        email: s.email,
      }),
    }
  )
);

export function authHeaders(): HeadersInit {
  const { token, userId } = useUserStore.getState();
  const h: Record<string, string> = {};
  if (token) {
    h["Authorization"] = `Bearer ${token}`;
    return h;
  }
  if (userId != null && userId > 0) h["X-User-Id"] = String(userId);
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
