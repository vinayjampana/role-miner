import { useState } from "react";
import { api } from "../api/client";
import { useUserStore } from "./userStore";

export function LoginPage() {
  const [tab, setTab] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [registrationToken, setRegistrationToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await api.auth.login(email, password);
      useUserStore.getState().setAuth(res.token, res.user_id, res.name, res.email);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  const onRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.auth.register(name, email, password, registrationToken);
      const res = await api.auth.login(email, password);
      useUserStore.getState().setAuth(res.token, res.user_id, res.name, res.email);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-full flex items-center justify-center bg-slate-50 p-4">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-lg shadow-sm p-6">
        <h1 className="text-xl font-semibold text-slate-900 mb-1">RoleMiner</h1>
        <p className="text-sm text-slate-500 mb-6">Sign in to continue</p>

        <div className="flex rounded-lg border border-slate-200 p-0.5 mb-6">
          <button
            type="button"
            onClick={() => {
              setTab("login");
              setError(null);
            }}
            className={`flex-1 py-2 text-sm font-medium rounded-md ${
              tab === "login" ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            Login
          </button>
          <button
            type="button"
            onClick={() => {
              setTab("register");
              setError(null);
            }}
            className={`flex-1 py-2 text-sm font-medium rounded-md ${
              tab === "register" ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            Register
          </button>
        </div>

        {error ? (
          <div className="mb-4 text-sm text-red-600 bg-red-50 border border-red-100 rounded px-3 py-2">
            {error}
          </div>
        ) : null}

        {tab === "login" ? (
          <form onSubmit={onLogin} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Email</label>
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full border border-slate-200 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Password</label>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full border border-slate-200 rounded px-3 py-2 text-sm"
              />
            </div>
            <button
              type="submit"
              disabled={busy}
              className="w-full py-2.5 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
            >
              {busy ? "…" : "Login"}
            </button>
          </form>
        ) : (
          <form onSubmit={onRegister} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Name</label>
              <input
                type="text"
                autoComplete="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="w-full border border-slate-200 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Email</label>
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full border border-slate-200 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Password</label>
              <input
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full border border-slate-200 rounded px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Registration token</label>
              <input
                type="password"
                autoComplete="off"
                value={registrationToken}
                onChange={(e) => setRegistrationToken(e.target.value)}
                required
                className="w-full border border-slate-200 rounded px-3 py-2 text-sm font-mono"
              />
            </div>
            <button
              type="submit"
              disabled={busy}
              className="w-full py-2.5 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
            >
              {busy ? "…" : "Create account"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
