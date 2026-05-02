import type { Job } from "../api/client";

const scoreColor = (s: number) =>
  s >= 7 ? "bg-green-500" : s >= 5 ? "bg-yellow-500" : "bg-red-500";

export function JobCard({ job, onClick }: { job: Job; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className="bg-white border border-slate-200 rounded-lg p-4 hover:shadow-md transition cursor-pointer"
    >
      <div className="flex items-start gap-3">
        <div
          className={`${scoreColor(
            job.score
          )} text-white font-bold text-lg w-10 h-10 rounded flex items-center justify-center shrink-0`}
        >
          {job.score}
        </div>
        <div className="flex-1 min-w-0">
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

          {(job.skill_gap?.have?.length || job.skill_gap?.gap?.length) ? (
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
            <div className="mt-2 text-xs text-slate-600 italic">"{job.reason}"</div>
          )}

          <div className="mt-3">
            <a
              href={job.url}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-block bg-slate-900 text-white text-xs font-medium px-3 py-1.5 rounded hover:bg-slate-700"
            >
              Apply
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
