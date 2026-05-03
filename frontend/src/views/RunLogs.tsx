import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { api, type RunDetail, type RunEvent } from "../api/client";
import { RunEventStream, useRunStream, type StreamEvent } from "../components/RunEventStream";
import { formatRunStartedAt } from "../lib/datetime";

const RUN_LOGS_SELECTED_KEY = "roleminer:run-logs-selected";

function readStoredRunId(): number | null {
  try {
    const s = sessionStorage.getItem(RUN_LOGS_SELECTED_KEY);
    if (!s) return null;
    const n = parseInt(s, 10);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function findEvent(events: RunEvent[], type: string): RunEvent | undefined {
  return events.find((e) => e.event_type === type);
}

/** Prefer latest SSE payload while a run is live so job snapshots update before refetch. */
function mergedEventData(
  evs: RunEvent[],
  liveEvs: StreamEvent[],
  isLive: boolean,
  type: string,
): Record<string, any> | undefined {
  const fromDb = findEvent(evs, type)?.data;
  if (!isLive) return fromDb;
  for (let i = liveEvs.length - 1; i >= 0; i--) {
    if (liveEvs[i].type === type) return liveEvs[i].data ?? {};
  }
  return fromDb;
}

type JobSnapshot = { total?: number; truncated?: boolean; items?: Array<Record<string, any>> };

function JobSnapshotTable({
  snapshot,
  emptyHint,
}: {
  snapshot?: JobSnapshot;
  emptyHint?: string;
}) {
  const items = snapshot?.items ?? [];
  if (!items.length) {
    return emptyHint ? <div className="text-xs text-slate-400 mt-2">{emptyHint}</div> : null;
  }
  const showRank = items.some((r) => r.rank_score != null);
  const showScore = items.some((r) => r.score != null);
  const total = snapshot?.total ?? items.length;
  const trunc = snapshot?.truncated;

  return (
    <div className="mt-3 border border-slate-100 rounded-lg overflow-hidden">
      <div className="px-3 py-1.5 bg-slate-50 text-xs text-slate-500 flex justify-between">
        <span>
          <strong className="text-slate-700">{total}</strong> job{total === 1 ? "" : "s"}
          {trunc ? <span className="text-amber-600 ml-2">(showing first {items.length})</span> : null}
        </span>
      </div>
      <div className="max-h-64 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="bg-slate-50/80 text-slate-500 sticky top-0">
            <tr>
              {showScore && <th className="text-left px-2 py-1.5 w-10">#</th>}
              {showRank && <th className="text-right px-2 py-1.5 w-16 font-mono">sim</th>}
              <th className="text-left px-2 py-1.5">Role</th>
              <th className="text-left px-2 py-1.5">Company</th>
              <th className="text-left px-2 py-1.5 w-8" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {items.map((r, i) => (
              <tr key={i} className="hover:bg-slate-50/80">
                {showScore && (
                  <td className="px-2 py-1 font-mono text-slate-600">{r.score ?? "—"}</td>
                )}
                {showRank && (
                  <td className="px-2 py-1 text-right font-mono text-indigo-700">{r.rank_score ?? "—"}</td>
                )}
                <td className="px-2 py-1 text-slate-800 max-w-[200px] truncate" title={String(r.title ?? "")}>
                  {r.title}
                </td>
                <td className="px-2 py-1 text-slate-500 max-w-[120px] truncate">{r.company}</td>
                <td className="px-2 py-1">
                  {r.url ? (
                    <a
                      href={String(r.url)}
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-600 hover:underline"
                    >
                      ↗
                    </a>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Sidebar ────────────────────────────────────────────────────────────────

export function RunLogs({ initialRunId }: { initialRunId?: number | null }) {
  const qc = useQueryClient();
  const { data: runs = [] } = useQuery({
    queryKey: ["runs"],
    queryFn: api.listRuns,
    refetchInterval: 5000,
    staleTime: 0,
    refetchOnMount: "always",
  });
  const [selected, setSelected] = useState<number | null>(() => initialRunId ?? readStoredRunId());

  const setSelectedPersist = (id: number | null) => {
    setSelected(id);
    try {
      if (id != null) sessionStorage.setItem(RUN_LOGS_SELECTED_KEY, String(id));
      else sessionStorage.removeItem(RUN_LOGS_SELECTED_KEY);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    if (!runs.length) return;
    const ids = new Set(runs.map((r) => r.id));
    const maxId = Math.max(...runs.map((r) => r.id));

    if (selected != null) {
      if (ids.has(selected)) return;
      if (selected > maxId) return;
    }

    const running = runs.find((r) => r.status === "running");
    const pick = running?.id ?? runs[0].id;
    if (pick !== selected) setSelectedPersist(pick);
  }, [runs, selected]);

  const trigger = async () => {
    const r = await api.trigger();
    qc.invalidateQueries({ queryKey: ["runs"] });
    setSelectedPersist(r.run_id);
  };

  return (
    <div className="flex h-full">
      <aside className="w-[280px] shrink-0 bg-white border-r border-slate-200 overflow-y-auto">
        <div className="p-3 border-b border-slate-200 sticky top-0 bg-white z-10">
          <button
            onClick={trigger}
            className="w-full bg-emerald-600 text-white py-2 rounded font-medium hover:bg-emerald-700"
          >
            ▶ Run Now
          </button>
        </div>
        {runs.map((r) => (
          <button
            key={r.id}
            onClick={() => setSelectedPersist(r.id)}
            className={`w-full text-left p-3 border-b border-slate-100 hover:bg-slate-50 ${selected === r.id ? "bg-blue-50 border-l-2 border-l-blue-500" : ""}`}
          >
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500">{formatRunStartedAt(r.timestamp)}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                r.status === "running" ? "bg-yellow-100 text-yellow-700 animate-pulse"
                : r.status === "failed" ? "bg-red-100 text-red-700"
                : "bg-green-100 text-green-700"
              }`}>{r.status ?? "?"}</span>
            </div>
            <div className="text-sm font-medium mt-0.5">#{r.id}: {r.jobs_found ?? 0} → {r.jobs_scored ?? 0} jobs</div>
            <div className="text-xs text-slate-400">${(r.cost_usd ?? 0).toFixed(4)} · {(r.duration_seconds ?? 0).toFixed(1)}s</div>
          </button>
        ))}
      </aside>

      <main className="flex-1 overflow-y-auto bg-slate-50 p-5">
        {selected != null
          ? <RunDetailView runId={selected} />
          : <div className="text-slate-400 text-center mt-20">Select a run or click Run Now</div>}
      </main>
    </div>
  );
}

// ─── Pipeline step tracker ───────────────────────────────────────────────────

type StepStatus = "pending" | "running" | "done" | "error";

interface PipelineStep {
  key: string;
  label: string;
  status: StepStatus;
  detail?: string;
}

function deriveSteps(evs: RunEvent[], liveEvs: StreamEvent[], isLive: boolean): PipelineStep[] {
  const all = isLive
    ? [...evs.map((e) => ({ type: e.event_type, data: e.data })), ...liveEvs.map((e) => ({ type: e.type, data: e.data ?? {} }))]
    : evs.map((e) => ({ type: e.event_type, data: e.data }));

  const has = (t: string) => {
    if (isLive && liveEvs.some((e) => e.type === t)) return true;
    return evs.some((e) => e.event_type === t);
  };
  const get = (t: string) => {
    if (isLive) {
      for (let i = liveEvs.length - 1; i >= 0; i--) {
        if (liveEvs[i].type === t) return liveEvs[i].data ?? {};
      }
    }
    return findEvent(evs, t)?.data ?? {};
  };

  const scrapeStarted = has("scrape_start") || has("scraper_start");
  const scraperCount = all.filter((e) => e.type === "scraper_done").length;
  const totalSources = (get("scrape_start") as any)?.total_sources ?? 0;
  const scrapeDoneEvt = has("scrape_done");
  const dedupDone = has("dedup_done") || has("filter_done");
  const dd = get("dedup_done") as any;
  const filterDone = has("filter_done");
  const roleDone = has("role_filter_done");
  const embedDone = has("embed_done");
  const rankDone = has("rank_done");
  const scoreDone = has("score_done");

  const fd = get("filter_done") as any;
  const rd = get("role_filter_done") as any;
  const ed = get("embed_done") as any;
  const rkd = get("rank_done") as any;
  const sd = get("score_done") as any;

  return [
    {
      key: "scrape",
      label: "Scrape",
      status: !scrapeStarted ? "pending" : !filterDone && isLive ? "running" : "done",
      detail: totalSources > 0 ? `${scraperCount}/${totalSources} sources` : scraperCount > 0 ? `${scraperCount} sources` : undefined,
    },
    {
      key: "dedup",
      label: "Dedup",
      status: !dedupDone ? (scrapeDoneEvt && isLive ? "running" : "pending") : "done",
      detail: dd?.total_in != null ? `${dd.total_in} → ${dd.total_out} (−${dd.removed ?? 0})` : undefined,
    },
    {
      key: "filter",
      label: "Filter",
      status: !filterDone ? (roleDone || rankDone || scoreDone ? "done" : scrapeStarted && !filterDone && isLive ? "pending" : "pending") : "done",
      detail: fd ? `${fd.total_in} → ${fd.total_out}` : undefined,
    },
    {
      key: "role",
      label: "Role filter",
      status: !roleDone ? "pending" : "done",
      detail: rd ? `${rd.total_in} → ${rd.total_out}` : undefined,
    },
    {
      key: "embed",
      label: "Embed",
      status: !embedDone ? (rankDone || scoreDone ? "done" : roleDone && isLive ? "running" : "pending") : "done",
      detail: ed ? `${ed.jobs_embedded} jobs` : undefined,
    },
    {
      key: "rank",
      label: "Rank",
      status: !rankDone ? (scoreDone ? "done" : embedDone && isLive ? "running" : "pending") : "done",
      detail: rkd ? `top ${(rkd.top_scores?.[0] ?? 0).toFixed(3)}` : undefined,
    },
    {
      key: "score",
      label: "Score",
      status: !scoreDone ? (rankDone && isLive ? "running" : "pending") : "done",
      detail: sd ? `${sd.jobs_scored} jobs · $${sd.cost_usd?.toFixed(4)}` : undefined,
    },
  ];
}

interface FunnelCounts {
  scraped: number | null;
  deduped: number | null;
  filtered: number | null;
  roleFiltered: number | null;
  ranked: number | null;
  scored: number | null;
}

function deriveFunnelCounts(
  evs: RunEvent[],
  liveEvs: StreamEvent[],
  isLive: boolean,
): FunnelCounts {
  const scrapeDone = mergedEventData(evs, liveEvs, isLive, "scrape_done");
  const dd = mergedEventData(evs, liveEvs, isLive, "dedup_done");
  const fd = mergedEventData(evs, liveEvs, isLive, "filter_done");
  const rd = mergedEventData(evs, liveEvs, isLive, "role_filter_done");
  const rkd = mergedEventData(evs, liveEvs, isLive, "rank_done");
  const sd = mergedEventData(evs, liveEvs, isLive, "score_done");

  return {
    scraped: scrapeDone?.total_jobs ?? scrapeDone?.scraped_count ?? null,
    deduped: dd?.total_out ?? dd?.deduped_count ?? null,
    filtered: fd?.total_out ?? fd?.filtered_count ?? null,
    roleFiltered: rd?.total_out ?? null,
    ranked: rkd?.total_ranked ?? rkd?.ranked_count ?? null,
    scored: sd?.jobs_scored ?? sd?.scored_count ?? null,
  };
}

function PipelineFunnel({ counts }: { counts: FunnelCounts }) {
  const stages: { key: string; label: string; count: number | null; color: string }[] = [
    { key: "scraped", label: "Scraped", count: counts.scraped, color: "bg-cyan-500" },
    { key: "deduped", label: "Deduped", count: counts.deduped, color: "bg-amber-500" },
    { key: "filtered", label: "Filtered", count: counts.filtered, color: "bg-purple-500" },
    { key: "roleFiltered", label: "Role Filtered", count: counts.roleFiltered, color: "bg-purple-400" },
    { key: "ranked", label: "Ranked", count: counts.ranked, color: "bg-indigo-500" },
    { key: "scored", label: "Scored", count: counts.scored, color: "bg-emerald-500" },
  ];

  const maxCount = Math.max(...stages.map((s) => s.count ?? 0), 1);
  const anyCount = stages.some((s) => s.count != null);

  if (!anyCount) return null;

  return (
    <div className="bg-white rounded-lg border border-slate-200 p-4">
      <div className="text-xs text-slate-500 font-medium mb-3 uppercase tracking-wide">Job Funnel</div>
      <div className="space-y-1.5">
        {stages.map((stage) => {
          const w = stage.count != null ? Math.max((stage.count / maxCount) * 100, 3) : 0;
          return (
            <div key={stage.key} className="flex items-center gap-3">
              <div className="text-xs text-slate-500 w-24 text-right shrink-0">{stage.label}</div>
              <div className="flex-1 bg-slate-100 rounded h-5 relative overflow-hidden">
                {stage.count != null && (
                  <div
                    className={`h-full rounded ${stage.color} transition-all duration-500`}
                    style={{ width: `${w}%` }}
                  />
                )}
                {stage.count != null && (
                  <span className="absolute inset-0 flex items-center justify-end pr-2 text-xs font-mono font-semibold text-slate-700">
                    {stage.count}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StepBadge({ step }: { step: PipelineStep }) {
  const icon = step.status === "done" ? "✓" : step.status === "running" ? "⟳" : step.status === "error" ? "✗" : "○";
  const colors = {
    done: "bg-emerald-100 text-emerald-800 border-emerald-200",
    running: "bg-blue-100 text-blue-800 border-blue-200 animate-pulse",
    error: "bg-red-100 text-red-800 border-red-200",
    pending: "bg-slate-100 text-slate-400 border-slate-200",
  };
  return (
    <div className={`border rounded px-3 py-2 text-center min-w-[90px] ${colors[step.status]}`}>
      <div className="text-base font-bold">{icon}</div>
      <div className="text-xs font-semibold">{step.label}</div>
      {step.detail && <div className="text-xs opacity-70">{step.detail}</div>}
    </div>
  );
}

// ─── Scraper progress table (live) ──────────────────────────────────────────

function ScraperTable({ evs, liveEvs, isLive }: { evs: RunEvent[]; liveEvs: StreamEvent[]; isLive: boolean }) {
  const all = isLive
    ? [...evs.map((e) => ({ type: e.event_type, data: e.data })), ...liveEvs.map((e) => ({ type: e.type, data: e.data ?? {} }))]
    : evs.map((e) => ({ type: e.event_type, data: e.data }));

  const startEvent = all.find((e) => e.type === "scrape_start");
  const allCompanies: string[] = (startEvent?.data as any)?.companies ?? [];

  const started = new Set(all.filter((e) => e.type === "scraper_start").map((e) => (e.data as any)?.company));
  const doneMap = new Map<string, any>();
  all.filter((e) => e.type === "scraper_done").forEach((e) => doneMap.set((e.data as any)?.company, e.data));
  const skippedMap = new Map<string, any>();
  all.filter((e) => e.type === "scraper_skipped").forEach((e) => skippedMap.set((e.data as any)?.company, e.data));
  const errorMap = new Map<string, string>();
  all.filter((e) => e.type === "error" && (e.data as any)?.step === "scraper").forEach((e) => errorMap.set((e.data as any)?.company, (e.data as any)?.error));

  const rows = allCompanies.length > 0
    ? allCompanies.map((name) => ({ name, done: doneMap.get(name), started: started.has(name), skipped: skippedMap.get(name), error: errorMap.get(name) }))
    : Array.from(doneMap.entries()).map(([name, d]) => ({ name, done: d, started: true, skipped: undefined, error: errorMap.get(name) }));

  if (rows.length === 0) return null;

  const fallbackCount = rows.filter((r) => r.done?.scraper_method === "playwright").length;

  return (
    <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <span className="font-semibold text-sm">Scrapers</span>
        <span className="text-xs text-slate-500">
          {doneMap.size}/{rows.length} done
          {fallbackCount > 0 && <span className="ml-2 text-amber-600">⚠ {fallbackCount} fallback</span>}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
            <tr>
              <th className="text-left px-4 py-2">Company</th>
              <th className="text-left px-4 py-2">ATS</th>
              <th className="text-left px-4 py-2">Method</th>
              <th className="text-right px-4 py-2">Jobs</th>
              <th className="text-right px-4 py-2">Time</th>
              <th className="text-left px-4 py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {rows.map(({ name, done, started, skipped, error }) => {
              const method = done?.scraper_method;
              const isFallback = method === "playwright";
              return (
                <tr key={name} className={!started && !skipped ? "opacity-40" : ""}>
                  <td className="px-4 py-2 font-medium">{name}</td>
                  <td className="px-4 py-2 text-slate-500 text-xs">{done?.ats ?? skipped?.ats ?? "—"}</td>
                  <td className="px-4 py-2 text-xs">
                    {method ? (
                      <span className={isFallback ? "text-amber-600 font-medium" : "text-slate-400"}>
                        {isFallback ? "⚠ Playwright" : "HTTP"}
                      </span>
                    ) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">{done ? done.jobs_fetched : skipped ? "—" : "—"}</td>
                  <td className="px-4 py-2 text-right text-slate-400 text-xs font-mono">{done ? `${done.duration_ms}ms` : "—"}</td>
                  <td className="px-4 py-2">
                    {error ? (
                      <span className="text-red-600 text-xs">{error.slice(0, 40)}</span>
                    ) : done ? (
                      <span className="text-emerald-600">✓</span>
                    ) : skipped ? (
                      <span className="text-slate-400 text-xs" title={`scraped ${skipped.last_scraped_hours_ago}h ago`}>⏭ fresh</span>
                    ) : started ? (
                      <span className="text-blue-500 animate-pulse text-xs">scraping…</span>
                    ) : (
                      <span className="text-slate-300 text-xs">pending</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Errors panel ───────────────────────────────────────────────────────────

interface ErrorEntry {
  step: string;
  company?: string;
  error: string;
  traceback?: string;
  ts?: string;
}

function collectErrors(evs: RunEvent[], liveEvs: StreamEvent[]): ErrorEntry[] {
  const entries: ErrorEntry[] = [];

  // explicit error events from DB
  for (const e of evs) {
    if (e.event_type === "error") {
      entries.push({
        step: e.data?.step ?? "unknown",
        company: e.data?.company,
        error: e.data?.error ?? "unknown error",
        traceback: e.data?.traceback,
        ts: e.ts,
      });
    }
    // scraper_done with error field
    if (e.event_type === "scraper_done" && e.data?.error) {
      entries.push({
        step: "scraper",
        company: e.data?.company,
        error: e.data.error,
        ts: e.ts,
      });
    }
  }

  // live stream errors not yet in DB
  for (const e of liveEvs) {
    if (e.type === "error") {
      entries.push({
        step: e.data?.step ?? "unknown",
        company: e.data?.company,
        error: e.data?.error ?? "unknown error",
        traceback: e.data?.traceback,
        ts: e.ts,
      });
    }
    if (e.type === "scraper_done" && e.data?.error) {
      entries.push({
        step: "scraper",
        company: e.data?.company,
        error: e.data.error,
        ts: e.ts,
      });
    }
  }

  // dedup by error message + company
  const seen = new Set<string>();
  return entries.filter((e) => {
    const key = `${e.step}:${e.company}:${e.error}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function ErrorsPanel({ evs, liveEvs }: { evs: RunEvent[]; liveEvs: StreamEvent[] }) {
  const errors = collectErrors(evs, liveEvs);
  if (errors.length === 0) return null;

  return (
    <div className="bg-red-50 border border-red-200 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-red-200 flex items-center gap-2">
        <span className="text-red-600 font-semibold text-sm">⚠ Errors ({errors.length})</span>
      </div>
      <div className="divide-y divide-red-100">
        {errors.map((err, i) => (
          <div key={i} className="px-4 py-3">
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 text-xs text-red-400 mb-1">
                  <span className="font-mono bg-red-100 px-1.5 py-0.5 rounded">{err.step}</span>
                  {err.company && <span className="font-medium text-red-600">{err.company}</span>}
                  {err.ts && <span className="text-red-300 ml-auto">{new Date(err.ts).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}</span>}
                </div>
                <div className="text-sm text-red-800 font-medium">{err.error}</div>
                {err.traceback && (
                  <details className="mt-1">
                    <summary className="text-xs text-red-400 cursor-pointer hover:text-red-600">traceback</summary>
                    <pre className="mt-1 text-xs bg-red-950 text-red-200 p-2 rounded overflow-x-auto whitespace-pre-wrap max-h-40">
                      {err.traceback}
                    </pre>
                  </details>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main detail view ────────────────────────────────────────────────────────

function RunDetailView({ runId }: { runId: number }) {
  const { data: detail, refetch, isError, error, isPending } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.runDetail(runId),
    refetchInterval: (q) => ((q.state.data as RunDetail | undefined)?.status === "running" ? 3000 : false),
  });

  const isLive = detail?.status === "running";
  const { events: liveEvs, done } = useRunStream(isLive ? runId : null);

  useEffect(() => { if (done) refetch(); }, [done, refetch]);

  if (isPending) return <div className="text-slate-400">Loading…</div>;
  if (isError) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 text-red-800 p-4 text-sm">
        <div className="font-semibold mb-1">Could not load run #{runId}</div>
        <div className="text-red-700/90">{error instanceof Error ? error.message : "Unknown error"}</div>
        <button
          type="button"
          onClick={() => refetch()}
          className="mt-3 text-xs px-2 py-1 rounded bg-red-100 hover:bg-red-200 text-red-900"
        >
          Retry
        </button>
      </div>
    );
  }
  if (!detail) return null;

  const evs = detail.events ?? [];
  const discover = mergedEventData(evs, liveEvs, !!isLive, "discover_done");
  const dedup = mergedEventData(evs, liveEvs, !!isLive, "dedup_done");
  const filt = mergedEventData(evs, liveEvs, !!isLive, "filter_done");
  const role = mergedEventData(evs, liveEvs, !!isLive, "role_filter_done");
  const embed = mergedEventData(evs, liveEvs, !!isLive, "embed_done");
  const rank = mergedEventData(evs, liveEvs, !!isLive, "rank_done");
  const score = mergedEventData(evs, liveEvs, !!isLive, "score_done");

  const steps = deriveSteps(evs, liveEvs, !!isLive);

  const filterChart = filt ? [
    { reason: "stale", count: filt.dropped_stale ?? 0 },
    { reason: "location", count: filt.dropped_location ?? 0 },
    { reason: "salary", count: filt.dropped_salary ?? 0 },
    { reason: "company type", count: filt.dropped_company_type ?? 0 },
    { reason: "blocklist", count: filt.dropped_blocklist ?? 0 },
  ] : [];

  const distChart = score?.score_distribution
    ? Object.entries(score.score_distribution).map(([bucket, count]) => ({ bucket, count }))
    : [];

  return (
    <div className="space-y-5 max-w-4xl">
      {/* Header */}
      <div className="flex items-center gap-3">
        <h2 className="text-xl font-bold">Run #{runId}</h2>
        {isLive && <span className="bg-red-500 text-white text-xs px-2 py-0.5 rounded-full animate-pulse font-medium">● LIVE</span>}
        <span className={`text-xs px-2 py-0.5 rounded ${
          detail.status === "running" ? "bg-yellow-100 text-yellow-700"
          : detail.status === "failed" ? "bg-red-100 text-red-700"
          : "bg-green-100 text-green-700"
        }`}>{detail.status}</span>
        {detail.duration_seconds && <span className="text-sm text-slate-500">{detail.duration_seconds.toFixed(1)}s</span>}
      </div>

      {/* Pipeline step tracker */}
      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="text-xs text-slate-500 font-medium mb-3 uppercase tracking-wide">Pipeline</div>
        <div className="flex items-center gap-1 flex-wrap">
          {steps.map((s, i) => (
            <div key={s.key} className="flex items-center">
              {i > 0 && <span className="text-slate-300 mx-0.5">→</span>}
              <StepBadge step={s} />
            </div>
          ))}
        </div>
      </div>

      {/* Job count funnel */}
      <PipelineFunnel counts={deriveFunnelCounts(evs, liveEvs, !!isLive)} />

      {/* Errors — shown immediately when any error arrives */}
      <ErrorsPanel evs={evs} liveEvs={liveEvs} />

      {/* Live terminal — always visible during run */}
      {isLive && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs text-slate-500 font-medium mb-3 uppercase tracking-wide flex items-center gap-2">
            Live output <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse inline-block" />
          </div>
          <RunEventStream events={liveEvs} />
        </div>
      )}

      {/* Scraper progress */}
      <ScraperTable evs={evs} liveEvs={liveEvs} isLive={!!isLive} />

      {/* URL deduplication */}
      {dedup && (dedup.total_in != null || dedup.jobs) && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs text-slate-500 font-medium mb-2 uppercase tracking-wide">Dedup by job URL</div>
          <div className="text-sm text-slate-700">
            <strong>{dedup.total_in ?? "—"}</strong> scraped → <strong>{dedup.total_out ?? "—"}</strong> unique
            {dedup.removed != null ? <span className="text-slate-400"> ({dedup.removed} duplicates removed)</span> : null}
          </div>
          <JobSnapshotTable snapshot={dedup.jobs as JobSnapshot} />
        </div>
      )}

      {/* Company discovery */}
      {discover && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs text-slate-500 font-medium mb-2 uppercase tracking-wide">Company discovery</div>
          {discover.new_companies > 0 ? (
            <>
              <div className="text-sm font-semibold text-emerald-700 mb-1">+{discover.new_companies} new companies added to registry</div>
              <div className="flex flex-wrap gap-1">
                {(discover.names as string[]).map((n) => (
                  <span key={n} className="bg-emerald-50 text-emerald-700 text-xs px-2 py-0.5 rounded-full border border-emerald-200">{n}</span>
                ))}
              </div>
            </>
          ) : (
            <div className="text-sm text-slate-400">No new companies discovered this run</div>
          )}
        </div>
      )}

      {/* Filter breakdown */}
      {filt && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs text-slate-500 font-medium mb-3 uppercase tracking-wide">Filter drops ({filt.total_in} → {filt.total_out} passed)</div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={filterChart} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="reason" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#6366f1" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          {filt.sample_dropped?.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-slate-400 cursor-pointer">Sample dropped jobs</summary>
              <ul className="mt-1 text-xs text-slate-500 space-y-0.5 pl-3">
                {(filt.sample_dropped as any[]).map((s, i) => (
                  <li key={i}>
                    {s.url ? (
                      <a href={s.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{s.title}</a>
                    ) : s.title}
                    {" @ "}{s.company} — <span className="text-slate-400">{s.reason}{s.age_days ? ` (${s.age_days}d old)` : ""}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <details className="mt-3">
            <summary className="text-xs font-semibold text-slate-600 cursor-pointer hover:text-slate-800">
              Jobs passing rule filter ({(filt.jobs_passed as JobSnapshot)?.total ?? filt.total_out ?? 0})
            </summary>
            <JobSnapshotTable snapshot={filt.jobs_passed as JobSnapshot} emptyHint="No jobs in this step." />
          </details>
        </div>
      )}

      {/* Role filter */}
      {role && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs text-slate-500 font-medium mb-2 uppercase tracking-wide">Role filter</div>
          <div className="text-sm">Dropped <strong>{role.dropped}</strong> non-eng roles from {role.total_in}. <strong>{role.total_out}</strong> remain.</div>
          {role.sample_dropped?.length > 0 && (
            <ul className="mt-2 text-xs text-slate-400 space-y-0.5 pl-3 list-disc">
              {(role.sample_dropped as any[]).map((s: any, i: number) => (
                <li key={i}>
                  {s.url ? (
                    <a href={s.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{s.title}</a>
                  ) : s.title}
                  {" @ "}{s.company}
                </li>
              ))}
            </ul>
          )}
          <details className="mt-3">
            <summary className="text-xs font-semibold text-slate-600 cursor-pointer hover:text-slate-800">
              Jobs passing role filter ({(role.jobs_passed as JobSnapshot)?.total ?? role.total_out ?? 0})
            </summary>
            <JobSnapshotTable snapshot={role.jobs_passed as JobSnapshot} emptyHint="No jobs in this step." />
          </details>
        </div>
      )}

      {/* Embed */}
      {embed && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs text-slate-500 font-medium mb-2 uppercase tracking-wide">Embedding</div>
          <div className="text-sm">
            <strong>{embed.jobs_embedded}</strong> jobs embedded → ChromaDB
            <span className="ml-2 text-xs text-slate-400">model: {embed.model}</span>
          </div>
        </div>
      )}

      {/* Ranker */}
      {rank && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs text-slate-500 font-medium mb-2 uppercase tracking-wide">Ranker — top similarity scores</div>
          <div className="flex flex-wrap gap-1.5">
            {(rank.top_scores as number[] ?? []).map((s, i) => (
              <span key={i} className={`text-xs px-2 py-1 rounded font-mono ${i === 0 ? "bg-indigo-100 text-indigo-800" : "bg-slate-100 text-slate-600"}`}>
                {s.toFixed(4)}
              </span>
            ))}
          </div>
          <div className="text-xs text-slate-400 mt-1">top {rank.sent_to_scorer} sent to scorer</div>
          <details className="mt-3">
            <summary className="text-xs font-semibold text-slate-600 cursor-pointer hover:text-slate-800">
              Ranked jobs ({(rank.jobs_ranked as JobSnapshot)?.total ?? rank.total_ranked ?? 0})
            </summary>
            <JobSnapshotTable snapshot={rank.jobs_ranked as JobSnapshot} emptyHint="No ranked jobs." />
          </details>
        </div>
      )}

      {/* Scorer */}
      {score && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs text-slate-500 font-medium mb-3 uppercase tracking-wide">Scorer</div>
          <div className="flex gap-6 text-sm mb-4">
            <div><span className="text-slate-500">jobs</span> <strong>{score.jobs_scored}</strong></div>
            <div><span className="text-slate-500">tokens</span> <strong>{score.tokens_used?.toLocaleString()}</strong></div>
            <div><span className="text-slate-500">cost</span> <strong>${score.cost_usd?.toFixed(5)}</strong></div>
          </div>
          <ResponsiveContainer width="100%" height={140}>
            <BarChart data={distChart} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#10b981" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-4">
            <div className="text-xs font-semibold text-slate-600 mb-2">Top 5 jobs</div>
            <div className="space-y-1.5">
              {(score.top_jobs as any[] ?? []).map((j, i) => (
                <div key={i} className="flex items-center gap-3 text-sm">
                  <span className={`font-bold text-xs px-1.5 py-0.5 rounded ${j.score >= 7 ? "bg-emerald-100 text-emerald-800" : j.score >= 4 ? "bg-yellow-100 text-yellow-800" : "bg-red-100 text-red-700"}`}>
                    {j.score}
                  </span>
                  <span>{j.title} <span className="text-slate-400">@</span> {j.company}</span>
                </div>
              ))}
            </div>
          </div>
          <details className="mt-3">
            <summary className="text-xs font-semibold text-slate-600 cursor-pointer hover:text-slate-800">
              All LLM-scored jobs ({(score.jobs_scored_detail as JobSnapshot)?.total ?? score.jobs_scored ?? 0})
            </summary>
            <JobSnapshotTable snapshot={score.jobs_scored_detail as JobSnapshot} emptyHint="No scored jobs." />
          </details>
          <details className="mt-4">
            <summary className="cursor-pointer text-xs text-slate-400 hover:text-slate-600">LLM prompt preview</summary>
            <pre className="bg-slate-950 text-slate-300 text-xs p-3 mt-2 rounded whitespace-pre-wrap overflow-x-auto max-h-40">
              {score.llm_prompt_preview}
            </pre>
          </details>
        </div>
      )}

      {/* Replay terminal for finished runs */}
      {!isLive && evs.length > 0 && (
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <div className="text-xs text-slate-500 font-medium mb-3 uppercase tracking-wide">Event log</div>
          <RunEventStream events={evs.map((e) => ({ type: e.event_type, source: e.source ?? undefined, data: e.data, ts: e.ts }))} />
        </div>
      )}
    </div>
  );
}
