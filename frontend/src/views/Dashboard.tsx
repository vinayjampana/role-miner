import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Job } from "../api/client";
import { JobCard } from "../components/JobCard";
import { JobDetail } from "../components/JobDetail";

export function Dashboard() {
  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ["jobs-latest"],
    queryFn: api.latestJobs,
  });

  const [minScore, setMinScore] = useState(0);
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
  const [active, setActive] = useState<Job | null>(null);

  const filtered = useMemo(() => {
    return jobs.filter((j) => {
      if (j.score < minScore) return false;
      if (j.work_mode && workModes[j.work_mode] === false) return false;
      if (j.company_type && companyTypes[j.company_type] === false) return false;
      if (esopOnly && !j.has_esop) return false;
      if (noticeOnly && !j.notice_compatible) return false;
      return true;
    });
  }, [jobs, minScore, workModes, companyTypes, esopOnly, noticeOnly]);

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <aside className="w-[250px] shrink-0 bg-white border-r border-slate-200 p-4 overflow-y-auto">
        <h2 className="font-semibold text-sm uppercase text-slate-500 mb-3">Filters</h2>

        <div className="mb-5">
          <label className="text-sm font-medium block mb-1">Min score: {minScore}</label>
          <input
            type="range"
            min="0"
            max="10"
            value={minScore}
            onChange={(e) => setMinScore(parseInt(e.target.value))}
            className="w-full"
          />
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

      {/* Job grid */}
      <main className="flex-1 overflow-y-auto p-4">
        <div className="text-sm text-slate-600 mb-3">
          {isLoading ? "Loading…" : `${filtered.length} of ${jobs.length} jobs`}
        </div>
        <div className="grid gap-3 grid-cols-1 lg:grid-cols-2 xl:grid-cols-3">
          {filtered.map((j) => (
            <JobCard key={j.url} job={j} onClick={() => setActive(j)} />
          ))}
        </div>
      </main>

      <JobDetail job={active} onClose={() => setActive(null)} />
    </div>
  );
}
