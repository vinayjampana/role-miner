import { useState } from "react";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { UserBootstrap } from "./auth/UserBootstrap";
import { useUserStore } from "./auth/userStore";
import { Companies } from "./views/Companies";
import { Dashboard } from "./views/Dashboard";
import { RunLogs } from "./views/RunLogs";
import { Settings } from "./views/Settings";
import { Tracker } from "./views/Tracker";

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } });

function NavAuth() {
  const queryClient = useQueryClient();
  const token = useUserStore((s) => s.token);
  const name = useUserStore((s) => s.name);
  const email = useUserStore((s) => s.email);

  if (!token) {
    return null;
  }

  const label = name?.trim() || email?.trim() || "Signed in";

  return (
    <div className="flex items-center gap-3 ml-auto">
      <span className="text-xs text-slate-600 max-w-[200px] truncate" title={email ?? name ?? undefined}>
        {label}
      </span>
      <button
        type="button"
        onClick={() => {
          useUserStore.getState().logout();
          queryClient.clear();
        }}
        className="text-sm px-3 py-1 rounded border border-slate-300 text-slate-700 hover:bg-slate-50"
      >
        Log out
      </button>
    </div>
  );
}

function AppInner() {
  const [view, setView] = useState<"dashboard" | "tracker" | "logs" | "companies" | "settings">("dashboard");
  const [selectRunId, setSelectRunId] = useState<number | null>(null);

  const navigateToRun = (runId: number) => {
    setSelectRunId(runId);
    setView("logs");
  };

  return (
    <div className="h-full flex flex-col">
      <nav className="bg-white border-b border-slate-200 px-4 py-2 flex items-center gap-4 flex-wrap">
        <div className="font-bold text-lg">RoleMiner</div>
        <div className="flex gap-1 flex-wrap">
          <button
            onClick={() => setView("dashboard")}
            className={`px-3 py-1 rounded text-sm ${
              view === "dashboard" ? "bg-slate-900 text-white" : "hover:bg-slate-100"
            }`}
          >
            Job Dashboard
          </button>
          <button
            onClick={() => setView("tracker")}
            className={`px-3 py-1 rounded text-sm ${
              view === "tracker" ? "bg-slate-900 text-white" : "hover:bg-slate-100"
            }`}
          >
            Tracker
          </button>
          <button
            onClick={() => setView("logs")}
            className={`px-3 py-1 rounded text-sm ${
              view === "logs" ? "bg-slate-900 text-white" : "hover:bg-slate-100"
            }`}
          >
            Run Logs
          </button>
          <button
            onClick={() => setView("companies")}
            className={`px-3 py-1 rounded text-sm ${
              view === "companies" ? "bg-slate-900 text-white" : "hover:bg-slate-100"
            }`}
          >
            Companies
          </button>
          <button
            onClick={() => setView("settings")}
            className={`px-3 py-1 rounded text-sm ${
              view === "settings" ? "bg-slate-900 text-white" : "hover:bg-slate-100"
            }`}
          >
            Profile &amp; LLM
          </button>
        </div>
        <NavAuth />
      </nav>
      <div className="flex-1 overflow-hidden">
        {view === "dashboard" ? (
          <Dashboard />
        ) : view === "tracker" ? (
          <Tracker />
        ) : view === "logs" ? (
          <RunLogs initialRunId={selectRunId} />
        ) : view === "companies" ? (
          <Companies onNavigateToRun={navigateToRun} />
        ) : (
          <Settings />
        )}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <UserBootstrap>
        <AppInner />
      </UserBootstrap>
    </QueryClientProvider>
  );
}
