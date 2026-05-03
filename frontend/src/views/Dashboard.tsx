import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Job } from "../api/client";
import { JobCard } from "../components/JobCard";
import { JobDetail } from "../components/JobDetail";
import { formatRunStartedAt } from "../lib/datetime";

const TRACKER_STATUS_KEYS = [
  "new",
  "clicked",
  "saved",
  "applied",
  "interviewing",
  "rejected",
  "dismissed",
  "archived",
] as const;

export function Dashboard() {
  const queryClient = useQueryClient();
  const [minScore, setMinScore] = useState(6);

  const { data: runs = [] } = useQuery({
    queryKey: ["active-run"],
    queryFn: () => api.listRuns(),
    refetchInterval: 1000,
  });
  const activeRun = runs.find((r) => r.status === "running") ?? null;

  useEffect(() => {
    if (!activeRun) queryClient.invalidateQueries({ queryKey: ["jobs-latest"] });
  }, [activeRun, queryClient]);

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ["jobs-latest", minScore],
    queryFn: () => api.latestJobs(minScore),
  });
  const [workModes, setWorkModes] = useState<Record<string, boolean>>({
    remote: true,
    hybrid: true,
    onsite: true,
  });
  const [companyTypes, setCompanyTypes] = useState<Record<string, boolean>>({
    product: true,
    service: true,
  });
  const [esopOnly, setEsopOnly] = useState(false);
  const [noticeOnly, setNoticeOnly] = useState(false);
  const [statusFilter, setStatusFilter] = useState(
    () => new Set<string>(["new", "clicked", "saved", "applied", "interviewing", "rejected"])
  );
  const [active, setActive] = useState<Job | null>(null);

  const filtered = useMemo(() => {
    return jobs.filter((j) => {
      const st = j.tracker_status || "new";
      if (!statusFilter.has(st)) return false;
      if (j.score < minScore) return false;
      if (j.work_mode && workModes[j.work_mode] === false) return false;
      if (j.company_type && companyTypes[j.company_type] === false) return false;
      if (esopOnly && !j.has_esop) return false;
      if (noticeOnly && !j.notice_compatible) return false;
      return true;
    });
  }, [jobs, minScore, workModes, companyTypes, esopOnly, noticeOnly, statusFilter]);

  const allStatusesActive = TRACKER_STATUS_KEYS.every((k) => statusFilter.has(k));

  return (
    <div className="flex h-full">
      <aside className="w-[250px] shrink-0 bg-white border-r border-slate-200 p-4 overflow-y-auto">
        <h2 className="font-semibold text-sm uppercase text-slate-500 mb-3">Filters</h2>

        <div className="mb-5">
          <label className="text-sm font-medium block mb-1">Min score: {minScore}</label>
          <input
            type="range"
            min="1"
            max="10"
            value={minScore}
            onChange={(e) => setMinScore(parseInt(e.target.value))}
            className="w-full"
          />
          <p className="text-xs text-slate-500 mt-1">Drag to filter by minimum LLM score (1–10).</p>
        </div>

        <div className="mb-5">
          <div className="text-sm font-medium mb-2">Status</div>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() =>
                setStatusFilter((prev) => {
                  if (TRACKER_STATUS_KEYS.every((k) => prev.has(k))) {
                    return new Set(["new", "clicked", "saved", "applied", "interviewing", "rejected"]);
                  }
                  return new Set(TRACKER_STATUS_KEYS);
                })
              }
              className={`text-xs px-2 py-1 rounded-full ${
                allStatusesActive ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              All
            </button>
            {TRACKER_STATUS_KEYS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() =>
                  setStatusFilter((prev) => {
                    const next = new Set(prev);
                    if (next.has(s)) next.delete(s);
                    else next.add(s);
                    return next;
                  })
                }
                className={`text-xs px-2 py-1 rounded-full capitalize ${
                  statusFilter.has(s) ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <div className="mb-5">
          <div className="text-sm font-medium mb-1">Work mode</div>
          {(["remote", "hybrid", "onsite"] as const).map((m) => (
            <label key={m} className="flex items-center gap-2 text-sm py-0.5">
              <input
                type="checkbox"
                checked={workModes[m]}
                onChange={(e) => setWorkModes({ ...workModes, [m]: e.target.checked })}
              />
              {m}
            </label>
          ))}
        </div>

        <div className="mb-5">
          <div className="text-sm font-medium mb-1">Company type</div>
          {(["product", "service"] as const).map((m) => (
            <label key={m} className="flex items-center gap-2 text-sm py-0.5">
              <input
                type="checkbox"
                checked={companyTypes[m]}
                onChange={(e) => setCompanyTypes({ ...companyTypes, [m]: e.target.checked })}
              />
              {m}
            </label>
          ))}
        </div>

        <label className="flex items-center gap-2 text-sm py-0.5">
          <input type="checkbox" checked={esopOnly} onChange={(e) => setEsopOnly(e.target.checked)} />
          ESOP only
        </label>
        <label className="flex items-center gap-2 text-sm py-0.5">
          <input type="checkbox" checked={noticeOnly} onChange={(e) => setNoticeOnly(e.target.checked)} />
          Notice compatible only
        </label>
      </aside>

      <main className="flex-1 overflow-y-auto flex flex-col">
        {activeRun ? (
          <div className="bg-blue-50 border-b border-blue-200 px-4 py-2 text-sm text-blue-800 flex items-center gap-2 shrink-0">
            <span className="animate-pulse w-2 h-2 rounded-full bg-blue-500 inline-block" />
            Run #{activeRun.id} in progress · started{" "}
            {formatRunStartedAt(activeRun.started_at ?? activeRun.timestamp)}
          </div>
        ) : null}
        <div className="p-4 flex-1 overflow-y-auto">
          <div className="text-sm text-slate-600 mb-3">
            {isLoading
              ? "Loading…"
              : `${filtered.length} of ${jobs.length} jobs (all runs for this profile, score ≥ ${minScore})`}
          </div>
          <div className="grid gap-3 grid-cols-1 lg:grid-cols-2 xl:grid-cols-3">
            {filtered.map((j) => (
              <JobCard key={j.url} job={j} onClick={() => setActive(j)} />
            ))}
          </div>
        </div>
      </main>

      <JobDetail job={active} onClose={() => setActive(null)} />
    </div>
  );
}
