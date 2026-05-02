export interface Job {
  title: string;
  company: string;
  url: string;
  date_posted: string;
  location: string;
  source: string;
  work_mode: string;
  salary_lpa: { min?: number; max?: number } | null;
  jd_text: string;
  funding_stage: string;
  has_esop: boolean;
  company_type: string;
  notice_compatible: boolean;
  score: number;
  reason: string;
  skill_gap: { have: string[]; need: string[]; gap: string[] };
}

export interface RunSummary {
  id: number;
  timestamp: string;
  status: string | null;
  duration_seconds: number | null;
  jobs_found: number | null;
  jobs_scored: number | null;
  tokens_used: number | null;
  cost_usd: number | null;
  output_file: string | null;
}

export interface RunEvent {
  id: number;
  run_id: number;
  ts: string;
  event_type: string;
  source: string | null;
  data: Record<string, any>;
}

export interface RunDetail extends RunSummary {
  events: RunEvent[];
}

export interface DiscoverResult {
  name: string;
  found: boolean;
  careers_url: string | null;
  ats_type: string | null;
  ats_slug: string | null;
  domain: string | null;
  method: "cache" | "heuristic" | "search" | "llm" | "failed";
  already_in_db: boolean;
  company_id: number | null;
}

export interface Company {
  id: number;
  name: string;
  domain: string | null;
  ats_type: string | null;
  careers_url: string | null;
  ats_slug: string | null;
  tech_stack: string[];
  location: string | null;
  hq_city: string | null;
  size_category: string | null;
  company_type: string | null;
  funding_stage: string | null;
  last_scraped_at: string | null;
  embedding_id: string | null;
}

const j = async <T>(p: Promise<Response>): Promise<T> => {
  const r = await p;
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
};

export const api = {
  latestJobs: () => j<Job[]>(fetch("/api/jobs/latest")),
  jobsForRun: (id: number) => j<Job[]>(fetch(`/api/jobs/run/${id}`)),
  listRuns: () => j<RunSummary[]>(fetch("/api/runs")),
  runDetail: (id: number) => j<RunDetail>(fetch(`/api/runs/${id}`)),
  trigger: () => j<{ run_id: number }>(fetch("/api/trigger", { method: "POST" })),
  stats: () => j<any>(fetch("/api/stats")),
  companies: () => j<Company[]>(fetch("/api/companies")),

  discoverCompanies: (names: string[], onResult: (r: DiscoverResult) => void): Promise<void> => {
    return new Promise(async (resolve, reject) => {
      try {
        const res = await fetch("/api/companies/discover", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ names }),
        });
        if (!res.ok || !res.body) { reject(new Error(`HTTP ${res.status}`)); return; }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          let eventType = "message";
          for (const line of lines) {
            if (line.startsWith("event:")) { eventType = line.slice(6).trim(); continue; }
            if (line.startsWith("data:")) {
              const data = line.slice(5).trim();
              if (eventType === "result") { try { onResult(JSON.parse(data)); } catch {} }
              if (eventType === "done") { resolve(); return; }
            }
          }
        }
        resolve();
      } catch (e) { reject(e); }
    });
  },
};
