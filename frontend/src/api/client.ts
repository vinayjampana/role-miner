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
};
