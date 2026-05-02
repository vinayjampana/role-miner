import type { Job } from "../api/client";

export function JobDetail({ job, onClose }: { job: Job | null; onClose: () => void }) {
  if (!job) return null;
  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/40" onClick={onClose} />
      <div className="w-[600px] max-w-full bg-white h-full shadow-2xl overflow-y-auto p-6">
        <div className="flex justify-between items-start mb-4">
          <div>
            <div className="text-sm text-slate-500">{job.company}</div>
            <h2 className="text-xl font-bold">{job.title}</h2>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-2xl">
            ×
          </button>
        </div>

        <div className="grid grid-cols-2 gap-2 text-sm mb-4">
          <div><span className="text-slate-500">Score:</span> <b>{job.score}/10</b></div>
          <div><span className="text-slate-500">Location:</span> {job.location}</div>
          <div><span className="text-slate-500">Work mode:</span> {job.work_mode}</div>
          <div><span className="text-slate-500">Source:</span> {job.source}</div>
          <div><span className="text-slate-500">Posted:</span> {job.date_posted?.slice(0, 10)}</div>
          <div><span className="text-slate-500">Type:</span> {job.company_type || "—"}</div>
          <div><span className="text-slate-500">ESOP:</span> {job.has_esop ? "Yes" : "—"}</div>
          <div><span className="text-slate-500">Notice ok:</span> {job.notice_compatible ? "Yes" : "No"}</div>
        </div>

        {job.reason && (
          <div className="bg-slate-50 border-l-4 border-blue-400 p-3 text-sm mb-4 italic">
            {job.reason}
          </div>
        )}

        {(job.skill_gap?.have?.length || job.skill_gap?.gap?.length) ? (
          <div className="mb-4">
            <div className="font-semibold text-sm mb-1">Skill match</div>
            <div className="flex flex-wrap gap-1">
              {(job.skill_gap.have || []).map((s) => (
                <span key={"h" + s} className="bg-green-100 text-green-800 px-2 py-0.5 rounded text-xs">{s}</span>
              ))}
              {(job.skill_gap.gap || []).map((s) => (
                <span key={"g" + s} className="bg-red-100 text-red-800 px-2 py-0.5 rounded text-xs">{s} (gap)</span>
              ))}
            </div>
          </div>
        ) : null}

        <a
          href={job.url}
          target="_blank"
          rel="noreferrer"
          className="block bg-slate-900 text-white text-center py-2 rounded font-medium mb-4"
        >
          Apply on company site
        </a>

        <div>
          <h3 className="font-semibold text-sm mb-2">Job description</h3>
          <pre className="whitespace-pre-wrap text-sm text-slate-700 bg-slate-50 p-3 rounded border border-slate-200">
            {job.jd_text || "(no description fetched)"}
          </pre>
        </div>
      </div>
    </div>
  );
}
