import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Companies } from "./views/Companies";
import { Dashboard } from "./views/Dashboard";
import { RunLogs } from "./views/RunLogs";
import { Settings } from "./views/Settings";

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } });

export default function App() {
  const [view, setView] = useState<"dashboard" | "logs" | "companies" | "settings">("dashboard");
  return (
    <QueryClientProvider client={qc}>
      <div className="h-full flex flex-col">
        <nav className="bg-white border-b border-slate-200 px-4 py-2 flex items-center gap-4">
          <div className="font-bold text-lg">RoleMiner</div>
          <div className="flex gap-1">
            <button
              onClick={() => setView("dashboard")}
              className={`px-3 py-1 rounded text-sm ${
                view === "dashboard" ? "bg-slate-900 text-white" : "hover:bg-slate-100"
              }`}
            >
              Job Dashboard
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
        </nav>
        <div className="flex-1 overflow-hidden">
          {view === "dashboard" ? (
            <Dashboard />
          ) : view === "logs" ? (
            <RunLogs />
          ) : view === "companies" ? (
            <Companies />
          ) : (
            <Settings />
          )}
        </div>
      </div>
    </QueryClientProvider>
  );
}
