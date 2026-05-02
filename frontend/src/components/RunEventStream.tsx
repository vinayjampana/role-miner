import { useEffect, useRef, useState } from "react";
import { formatEventLogTime } from "../lib/datetime";

export interface StreamEvent {
  type: string;
  source?: string;
  data?: Record<string, any>;
  ts?: string;
}

export function useRunStream(runId: number | null) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (runId == null) return;
    setEvents([]);
    setDone(false);
    const es = new EventSource(`/api/stream/${runId}`);
    es.onmessage = (msg) => {
      try {
        const ev = JSON.parse(msg.data) as StreamEvent;
        if (ev.type === "done") { setDone(true); es.close(); return; }
        if (ev.type === "ping") return;
        setEvents((prev) => [...prev, { ...ev, ts: new Date().toISOString() }]);
      } catch { /* ignore */ }
    };
    es.onerror = () => { es.close(); setDone(true); };
    return () => es.close();
  }, [runId]);

  return { events, done };
}

function eventLabel(ev: StreamEvent): { color: string; text: string } {
  const d = ev.data ?? {};
  switch (ev.type) {
    case "scrape_start":
      return { color: "text-cyan-400", text: `starting ${d.total_sources} sources: ${(d.companies as string[] ?? []).slice(0, 3).join(", ")}${(d.companies?.length ?? 0) > 3 ? "…" : ""}` };
    case "scraper_start":
      return { color: "text-blue-300", text: `scraping ${d.company} (${d.ats})…` };
    case "scraper_skipped":
      return { color: "text-slate-500", text: `skip ${d.company} — scraped ${d.last_scraped_hours_ago}h ago (fresh < ${d.freshness_hours}h)` };
    case "scraper_done":
      return {
        color: d.error ? "text-red-400" : d.jobs_fetched > 0 ? "text-emerald-400" : "text-slate-400",
        text: d.error
          ? `${d.company}: ERROR — ${d.error}`
          : `${d.company}: ${d.jobs_fetched} jobs (${d.duration_ms}ms)`,
      };
    case "discover_done":
      return {
        color: d.new_companies > 0 ? "text-yellow-300" : "text-slate-500",
        text: d.new_companies > 0
          ? `discovered ${d.new_companies} new companies: ${(d.names as string[]).join(", ")}`
          : "no new companies discovered",
      };
    case "filter_done":
      return { color: "text-purple-400", text: `filter: ${d.total_in} → ${d.total_out} (stale:${d.dropped_stale} loc:${d.dropped_location} salary:${d.dropped_salary})` };
    case "role_filter_done":
      return { color: "text-purple-300", text: `role filter: ${d.total_in} → ${d.total_out} (dropped ${d.dropped})` };
    case "embed_done":
      return { color: "text-teal-400", text: `embedded ${d.jobs_embedded} jobs → ChromaDB` };
    case "rank_done":
      return { color: "text-indigo-400", text: `ranked ${d.total_ranked}, top score ${(d.top_scores?.[0] ?? 0).toFixed(3)}, sending ${d.sent_to_scorer} to scorer` };
    case "score_done":
      return { color: "text-emerald-300", text: `scored ${d.jobs_scored} jobs · ${d.tokens_used} tokens · $${d.cost_usd?.toFixed(5)}` };
    case "error":
      return { color: "text-red-500", text: `ERROR [${d.step}]: ${d.error}` };
    default:
      return { color: "text-slate-400", text: JSON.stringify(d).slice(0, 80) };
  }
}

export function RunEventStream({ events }: { events: StreamEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div className="font-mono text-xs bg-slate-950 text-slate-200 p-3 rounded max-h-[400px] overflow-y-auto">
      {events.length === 0 && (
        <div className="text-slate-600">waiting for events…</div>
      )}
      {events.map((ev, i) => {
        const { color, text } = eventLabel(ev);
        const ts = ev.ts ? formatEventLogTime(ev.ts) : "";
        return (
          <div key={i} className="flex gap-2 leading-5">
            <span className="text-slate-600 shrink-0">{ts}</span>
            <span className={`shrink-0 w-28 truncate ${color}`}>{ev.type}</span>
            <span className="text-slate-300">{text}</span>
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
