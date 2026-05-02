import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Job } from "../api/client";
import { JobCard } from "../components/JobCard";
import { JobDetail } from "../components/JobDetail";

const ORDER = [
  "applied",
  "interviewing",
  "saved",
  "clicked",
  "new",
  "rejected",
  "dismissed",
  "archived",
] as const;

const SECTION_LABEL: Record<string, string> = {
  applied: "Applied",
  interviewing: "Interviewing",
  saved: "Saved for later",
  clicked: "Opened (clicked link)",
  new: "New",
  rejected: "Rejected",
  dismissed: "Dismissed",
  archived: "Archived",
};

export function Tracker() {
  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ["jobs-tracked"],
    queryFn: api.trackedJobs,
  });
  const [active, setActive] = useState<Job | null>(null);

  const grouped = useMemo(() => {
    const m = new Map<string, Job[]>();
    for (const s of ORDER) m.set(s, []);
    for (const j of jobs) {
      const st = j.tracker_status || "new";
      if (!m.has(st)) m.set(st, []);
      m.get(st)!.push(j);
    }
    return m;
  }, [jobs]);

  return (
    <div className="h-full overflow-y-auto bg-slate-50 p-4">
      <h1 className="text-lg font-semibold text-slate-900 mb-1">Application tracker</h1>
      <p className="text-sm text-slate-600 mb-4">
        Jobs you have opened or marked from the dashboard (same data as job status on each card).
      </p>
      {isLoading ? (
        <div className="text-slate-500">Loading…</div>
      ) : jobs.length === 0 ? (
        <div className="text-slate-500 text-sm">No tracked jobs yet — open the Job Dashboard and use Apply or set a status.</div>
      ) : (
        <div className="space-y-8 max-w-5xl">
          {ORDER.map((status) => {
            const list = grouped.get(status) ?? [];
            if (!list.length) return null;
            return (
              <section key={status}>
                <h2 className="text-sm font-semibold text-slate-500 mb-2">
                  {SECTION_LABEL[status] ?? status}{" "}
                  <span className="font-normal text-slate-400">({list.length})</span>
                </h2>
                <div className="grid gap-3 grid-cols-1 md:grid-cols-2">
                  {list.map((j) => (
                    <JobCard key={j.url} job={j} onClick={() => setActive(j)} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
      <JobDetail job={active} onClose={() => setActive(null)} />
    </div>
  );
}
