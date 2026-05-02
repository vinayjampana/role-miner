import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { api, type RunDetail, type RunEvent } from "../api/client";
import { RunEventStream, useRunStream } from "../components/RunEventStream";

function findEvent(events: RunEvent[], type: string): RunEvent | undefined {
  return events.find((e) => e.event_type === type);
}

export function RunLogs() {
  const qc = useQueryClient();
  const { data: runs = [] } = useQuery({
    queryKey: ["runs"],
    queryFn: api.listRuns,
    refetchInterval: 5000,
  });
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    if (selected == null && runs.length) setSelected(runs[0].id);
  }, [runs, selected]);

  const trigger = async () => {
    const r = await api.trigger();
    qc.invalidateQueries({ queryKey: ["runs"] });
    setSelected(r.run_id);
  };

  return (
    <div className="flex h-full">
      <aside className="w-[320px] shrink-0 bg-white border-r border-slate-200 overflow-y-auto">
        <div className="p-3 border-b border-slate-200 sticky top-0 bg-white">
          <button
            onClick={trigger}
            className="w-full bg-emerald-600 text-white py-2 rounded font-medium hover:bg-emerald-700"
          >
            Run Now
          </button>
        </div>
        <div>
          {runs.map((r) => (
            <button
              key={r.id}
              onClick={() => setSelected(r.id)}
              className={`w-full text-left p-3 border-b border-slate-100 hover:bg-slate-50 ${
                selected === r.id ? "bg-blue-50" : ""
              }`}
            >
              <div className="flex justify-between items-center">
                <div className="text-xs text-slate-500">{r.timestamp.slice(0, 19).replace("T", " ")}</div>
                <span
                  className={`text-xs px-1.5 py-0.5 rounded ${
                    r.status === "running"
                      ? "bg-yellow-100 text-yellow-800 animate-pulse"
                      : r.status === "failed"
                      ? "bg-red-100 text-red-800"
                      : "bg-green-100 text-green-800"
                  }`}
                >
                  {r.status || "?"}
                </span>
              </div>
              <div className="text-sm mt-1">
                #{r.id}: {r.jobs_found ?? 0} → {r.jobs_scored ?? 0}
              </div>
              <div className="text-xs text-slate-500">
                ${(r.cost_usd ?? 0).toFixed(4)} · {(r.duration_seconds ?? 0).toFixed(1)}s
              </div>
            </button>
          ))}
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto p-4">
        {selected != null ? <RunDetailView runId={selected} /> : <div className="text-slate-500">Select a run</div>}
      </main>
    </div>
  );
}

function RunDetailView({ runId }: { runId: number }) {
  const { data: detail, refetch } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.runDetail(runId),
    refetchInterval: (q) => {
      const d = q.state.data as RunDetail | undefined;
      return d?.status === "running" ? 2000 : false;
    },
  });

  const isLive = detail?.status === "running";
  const { events: liveEvents, done } = useRunStream(isLive ? runId : null);

  useEffect(() => {
    if (done) refetch();
  }, [done, refetch]);

  if (!detail) return <div>Loading…</div>;

  const evs = detail.events || [];
  const scraperEvents = evs.filter((e) => e.event_type === "scraper_done");
  const filt = findEvent(evs, "filter_done")?.data;
  const role = findEvent(evs, "role_filter_done")?.data;
  const rank = findEvent(evs, "rank_done")?.data;
  const score = findEvent(evs, "score_done")?.data;

  const filterChartData = filt
    ? [
        { reason: "stale", count: filt.dropped_stale || 0 },
        { reason: "location", count: filt.dropped_location || 0 },
        { reason: "salary", count: filt.dropped_salary || 0 },
        { reason: "ctype", count: filt.dropped_company_type || 0 },
        { reason: "block", count: filt.dropped_blocklist || 0 },
      ]
    : [];

  const distData = score?.score_distribution
    ? Object.entries(score.score_distribution).map(([bucket, count]) => ({ bucket, count }))
    : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h2 className="text-xl font-bold">Run #{runId}</h2>
        {isLive && (
          <span className="bg-red-500 text-white text-xs px-2 py-0.5 rounded animate-pulse">LIVE</span>
        )}
      </div>

      {/* Pipeline summary bar */}
      <div className="bg-white rounded border border-slate-200 p-4">
        <div className="text-sm text-slate-500 mb-2">Pipeline</div>
        <div className="flex items-center gap-2 text-sm">
          <Step label="raw" value={filt?.total_in ?? detail.jobs_found ?? 0} />
          <span>→</span>
          <Step label="filtered" value={filt?.total_out ?? 0} />
          <span>→</span>
          <Step label="role" value={role?.total_out ?? 0} />
          <span>→</span>
          <Step label="ranked" value={rank?.total_ranked ?? 0} />
          <span>→</span>
          <Step label="scored" value={score?.jobs_scored ?? 0} />
        </div>
      </div>

      {isLive && (
        <div className="bg-white rounded border border-slate-200 p-4">
          <div className="font-semibold text-sm mb-2">Live event stream</div>
          <RunEventStream events={liveEvents} />
        </div>
      )}

      {/* Scraper table */}
      <div className="bg-white rounded border border-slate-200 p-4">
        <div className="font-semibold text-sm mb-2">Scrapers ({scraperEvents.length})</div>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
            <tr>
              <th className="text-left p-1">Company</th>
              <th className="text-left p-1">ATS</th>
              <th className="text-right p-1">Jobs</th>
              <th className="text-right p-1">ms</th>
              <th className="text-left p-1">Error</th>
            </tr>
          </thead>
          <tbody>
            {scraperEvents.map((e) => (
              <tr key={e.id} className="border-t border-slate-100">
                <td className="p-1">{e.data.company}</td>
                <td className="p-1 text-slate-500">{e.data.ats}</td>
                <td className="p-1 text-right">{e.data.jobs_fetched}</td>
                <td className="p-1 text-right text-slate-500">{e.data.duration_ms}</td>
                <td className="p-1 text-red-600">{e.data.error || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Filter breakdown */}
      {filt && (
        <div className="bg-white rounded border border-slate-200 p-4">
          <div className="font-semibold text-sm mb-2">Filter drops</div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={filterChartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="reason" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Role filter */}
      {role && (
        <div className="bg-white rounded border border-slate-200 p-4">
          <div className="font-semibold text-sm mb-2">Role filter</div>
          <div className="text-sm text-slate-700">
            Dropped {role.dropped} of {role.total_in}.
          </div>
          <ul className="mt-1 text-xs text-slate-500 list-disc pl-5">
            {(role.sample_dropped || []).map((s: any, i: number) => (
              <li key={i}>{s.title} @ {s.company}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Ranker */}
      {rank && (
        <div className="bg-white rounded border border-slate-200 p-4">
          <div className="font-semibold text-sm mb-2">Top TF-IDF scores</div>
          <div className="flex flex-wrap gap-2 text-xs">
            {(rank.top_scores || []).map((s: number, i: number) => (
              <span key={i} className="bg-slate-100 px-2 py-1 rounded">
                {s.toFixed(3)}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Scorer */}
      {score && (
        <div className="bg-white rounded border border-slate-200 p-4">
          <div className="font-semibold text-sm mb-2">Scorer</div>
          <div className="text-sm mb-2">
            {score.jobs_scored} jobs · {score.tokens_used} tokens · ${score.cost_usd?.toFixed(6)}
          </div>
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={distData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="bucket" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#10b981" />
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-3 text-sm">
            <div className="font-semibold mb-1">Top jobs</div>
            <ul className="text-xs space-y-0.5">
              {(score.top_jobs || []).map((j: any, i: number) => (
                <li key={i}>
                  <b>{j.score}</b> — {j.title} @ {j.company}
                </li>
              ))}
            </ul>
          </div>

          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-slate-500">LLM prompt preview</summary>
            <pre className="bg-slate-50 text-xs p-2 mt-1 whitespace-pre-wrap">
              {score.llm_prompt_preview}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}

function Step({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-slate-100 rounded px-2 py-1">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-semibold">{value}</div>
    </div>
  );
}
