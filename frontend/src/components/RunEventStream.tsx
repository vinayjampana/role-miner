import { useEffect, useState } from "react";

export interface StreamEvent {
  type: string;
  source?: string;
  data?: Record<string, any>;
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
        if (ev.type === "done") {
          setDone(true);
          es.close();
          return;
        }
        if (ev.type === "ping") return;
        setEvents((prev) => [...prev, ev]);
      } catch {
        // ignore
      }
    };
    es.onerror = () => {
      es.close();
      setDone(true);
    };
    return () => es.close();
  }, [runId]);

  return { events, done };
}

export function RunEventStream({ events }: { events: StreamEvent[] }) {
  return (
    <div className="space-y-1 font-mono text-xs max-h-[300px] overflow-y-auto bg-slate-900 text-slate-100 p-3 rounded">
      {events.map((ev, i) => (
        <div key={i}>
          <span className="text-emerald-400">{ev.type}</span>{" "}
          {ev.source && <span className="text-blue-300">[{ev.source}]</span>}{" "}
          <span className="text-slate-300">
            {ev.type === "scraper_done"
              ? `${ev.data?.jobs_fetched} jobs (${ev.data?.duration_ms}ms)`
              : ev.type === "filter_done"
              ? `${ev.data?.total_in} → ${ev.data?.total_out}`
              : ev.type === "role_filter_done"
              ? `${ev.data?.total_in} → ${ev.data?.total_out}`
              : ev.type === "rank_done"
              ? `ranked ${ev.data?.total_ranked}, sending ${ev.data?.sent_to_scorer}`
              : ev.type === "score_done"
              ? `scored ${ev.data?.jobs_scored}, $${ev.data?.cost_usd?.toFixed?.(4)}`
              : ev.type === "error"
              ? `ERROR: ${ev.data?.error}`
              : ""}
          </span>
        </div>
      ))}
      {events.length === 0 && <div className="text-slate-500">Waiting for events…</div>}
    </div>
  );
}
