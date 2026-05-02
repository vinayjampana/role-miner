import { useState } from "react";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserBootstrap } from "./auth/UserBootstrap";
import { useUserStore } from "./auth/userStore";
import { api, type AppUser } from "./api/client";
import { Companies } from "./views/Companies";
import { Dashboard } from "./views/Dashboard";
import { RunLogs } from "./views/RunLogs";
import { Settings } from "./views/Settings";
import { Tracker } from "./views/Tracker";

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } });

function UserPicker() {
  const queryClient = useQueryClient();
  const userId = useUserStore((s) => s.userId);
  const setUserId = useUserStore((s) => s.setUserId);
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");

  const { data: users = [] } = useQuery({
    queryKey: ["users"],
    queryFn: api.listUsers,
    staleTime: 30_000,
  });

  const onSwitch = (id: number) => {
    setUserId(id);
    queryClient.invalidateQueries();
  };

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    const u = await api.createUser(name);
    setNewName("");
    setShowNew(false);
    await queryClient.invalidateQueries({ queryKey: ["users"] });
    onSwitch(u.id);
  };

  const current = users.find((u: AppUser) => u.id === userId);

  return (
    <div className="flex items-center gap-2 ml-auto">
      <label className="text-xs text-slate-500 whitespace-nowrap">User</label>
      <select
        className="text-sm border border-slate-200 rounded px-2 py-1 bg-white max-w-[160px]"
        value={userId ?? ""}
        onChange={(e) => onSwitch(parseInt(e.target.value, 10))}
      >
        {users.map((u: AppUser) => (
          <option key={u.id} value={u.id}>
            {u.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="text-xs text-blue-600 hover:underline"
        onClick={() => setShowNew((v) => !v)}
      >
        + New
      </button>
      {showNew && (
        <form onSubmit={onCreate} className="flex items-center gap-1">
          <input
            className="text-xs border border-slate-200 rounded px-2 py-1 w-28"
            placeholder="Name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button type="submit" className="text-xs bg-slate-900 text-white px-2 py-1 rounded">
            Add
          </button>
        </form>
      )}
      {current && (
        <span className="text-xs text-slate-400 hidden sm:inline">#{current.id}</span>
      )}
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
        <UserPicker />
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
