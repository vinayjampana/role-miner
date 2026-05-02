import { useQueryClient } from "@tanstack/react-query";
import type { Job } from "../api/client";
import { api } from "../api/client";

const scoreColor = (s: number) =>
  s >= 7 ? "bg-green-500" : s >= 5 ? "bg-yellow-500" : "bg-red-500";

const statusBadge = (st: string | undefined) => {
  const s = st || "new";
  if (s === "new") return null;
  const colors: Record<string, string> = {
    clicked: "bg-sky-100 text-sky-800",
    saved: "bg-violet-100 text-violet-800",
    archived: "bg-stone-200 text-stone-700",
    applied: "bg-emerald-100 text-emerald-800",
    interviewing: "bg-amber-100 text-amber-900",
    rejected: "bg-slate-200 text-slate-700",
    dismissed: "bg-slate-100 text-slate-500 line-through",
  };
  const cls = colors[s] || "bg-slate-100 text-slate-700";
  return (
    <span className={`text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded ${cls}`}>{s}</span>
  );
};

const quickBtn =
  "text-xs font-medium px-2 py-1 rounded border border-slate-200 bg-white text-slate-700 hover:bg-slate-50";

export function JobCard({ job, onClick }: { job: Job; onClick: () => void }) {
  const qc = useQueryClient();

  const invalidateJobQueries = () => {
    qc.invalidateQueries({ queryKey: ["jobs-latest"] });
    qc.invalidateQueries({ queryKey: ["jobs-tracked"] });
  };

  const setTrackerStatus = async (e: React.MouseEvent, status: string) => {
    e.stopPropagation();
    try {
      await api.setJobStatus(job.url, status, job.tracker_notes || "");
      invalidateJobQueries();
    } catch {
      /* ignore */
    }
  };

  const onApply = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await api.clickJob(job.url);
      invalidateJobQueries();
    } catch {
      /* ignore */
    }
    window.open(job.url, "_blank", "noreferrer");
  };

  return (
    <div
      onClick={onClick}
      className="bg-white border border-slate-200 rounded-lg p-4 hover:shadow-md transition cursor-pointer relative"
    >
      <div className="absolute top-3 right-3">{statusBadge(job.tracker_status)}</div>
      <div className="flex items-start gap-3">
        <div
          className={`${scoreColor(
            job.score
          )} text-white font-bold text-lg w-10 h-10 rounded flex items-center justify-center shrink-0`}
        >
          {job.score}
        </div>
        <div className="flex-1 min-w-0 pr-16">
          <div className="text-sm text-slate-500">{job.company}</div>
          <div className="font-semibold text-slate-900 truncate">{job.title}</div>

          <div className="flex flex-wrap gap-2 mt-2 text-xs">
            <span className="bg-slate-100 px-2 py-0.5 rounded">{job.location || "—"}</span>
            <span className="bg-blue-100 text-blue-700 px-2 py-0.5 rounded">{job.work_mode}</span>
            {job.has_esop && (
              <span className="bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded">ESOP</span>
            )}
            {!job.notice_compatible && (
              <span className="bg-orange-100 text-orange-700 px-2 py-0.5 rounded">Notice ⚠</span>
            )}
            {job.salary_lpa && (
              <span className="bg-violet-100 text-violet-700 px-2 py-0.5 rounded">
                {job.salary_lpa.min ?? "?"}–{job.salary_lpa.max ?? "?"} LPA
              </span>
            )}
          </div>

          {job.skill_gap?.have?.length || job.skill_gap?.gap?.length ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {(job.skill_gap.have || []).map((s) => (
                <span key={"h" + s} className="text-xs bg-green-100 text-green-800 px-1.5 py-0.5 rounded">
                  {s}
                </span>
              ))}
              {(job.skill_gap.gap || []).map((s) => (
                <span key={"g" + s} className="text-xs bg-red-100 text-red-800 px-1.5 py-0.5 rounded">
                  {s}
                </span>
              ))}
            </div>
          ) : null}

          {job.reason && (
            <div className="mt-2 text-xs text-slate-600 italic">&quot;{job.reason}&quot;</div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onApply}
              className="inline-block bg-slate-900 text-white text-xs font-medium px-3 py-1.5 rounded hover:bg-slate-700"
            >
              Apply
            </button>
            <button type="button" className={quickBtn} onClick={(e) => setTrackerStatus(e, "saved")}>
              Save for later
            </button>
            <button type="button" className={quickBtn} onClick={(e) => setTrackerStatus(e, "archived")}>
              Archive
            </button>
            <button type="button" className={quickBtn} onClick={(e) => setTrackerStatus(e, "applied")}>
              Mark applied
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
