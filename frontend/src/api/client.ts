import { authFetch } from "../auth/userStore";

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
  tracker_status?: string;
  tracker_notes?: string;
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

export interface SearchProfile {
  skills: string[];
  locations: string[];
  salary_min_lpa: number;
  work_mode: string[];
  company_type: string[];
  exclude_companies: string[];
  notice_days: number;
  resume_summary: string;
}

export interface RuntimeSettings {
  llm_base_url: string;
  scoring_model: string;
  discover_model: string;
  embed_base_url: string;
  embed_model: string;
  scraper_freshness_hours: number;
  proxy_url: string;
  llm_api_key_set: boolean;
  llm_api_key_hint: string;
  embed_api_key_set: boolean;
  embed_api_key_hint: string;
  brave_search_api_key_set: boolean;
  brave_search_api_key_hint: string;
}

export interface RuntimeSettingsPatch {
  llm_api_key?: string;
  llm_base_url?: string;
  scoring_model?: string;
  discover_model?: string;
  embed_api_key?: string;
  embed_base_url?: string;
  embed_model?: string;
  brave_search_api_key?: string;
  scraper_freshness_hours?: number;
  proxy_url?: string;
}

export interface ResumeInfo {
  has_pdf: boolean;
  path: string;
}

export interface AppUser {
  id: number;
  name: string;
  email: string | null;
  active_profile_id: number | null;
}

export const api = {
  listUsers: () => j<AppUser[]>(authFetch("/api/users")),
  createUser: (name: string, email?: string) =>
    j<AppUser>(
      authFetch("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email: email || null }),
      })
    ),

  latestJobs: (minScore = 6) =>
    j<Job[]>(authFetch(`/api/jobs/latest?min_score=${encodeURIComponent(minScore)}`)),
  jobsForRun: (id: number) => j<Job[]>(authFetch(`/api/jobs/run/${id}`)),
  trackedJobs: () => j<Job[]>(authFetch("/api/jobs/tracked")),
  setJobStatus: (url: string, status: string, notes?: string) =>
    j<{ ok: boolean }>(
      authFetch("/api/jobs/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, status, notes: notes ?? null }),
      })
    ),
  clickJob: (url: string) =>
    j<{ ok: boolean }>(
      authFetch("/api/jobs/click", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      })
    ),

  listRuns: () => j<RunSummary[]>(authFetch("/api/runs")),
  runDetail: (id: number) => j<RunDetail>(authFetch(`/api/runs/${id}`)),
  trigger: () => j<{ run_id: number }>(authFetch("/api/trigger", { method: "POST" })),
  stats: () => j<any>(authFetch("/api/stats")),
  companies: () => j<Company[]>(authFetch("/api/companies")),

  getProfile: () => j<SearchProfile>(authFetch("/api/profile")),
  putProfile: (body: SearchProfile) =>
    j<SearchProfile>(
      authFetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    ),
  getRuntimeSettings: () => j<RuntimeSettings>(authFetch("/api/settings")),
  patchRuntimeSettings: (patch: RuntimeSettingsPatch) =>
    j<RuntimeSettings>(
      authFetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      })
    ),
  getResumeInfo: () => j<ResumeInfo>(authFetch("/api/profile/resume")),
  uploadResume: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await authFetch("/api/profile/resume", { method: "POST", body: fd });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<{ ok: boolean; path: string; bytes: number }>;
  },

  discoverCompanies: (names: string[], onResult: (r: DiscoverResult) => void): Promise<void> => {
    return new Promise(async (resolve, reject) => {
      try {
        const res = await authFetch("/api/companies/discover", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ names }),
        });
        if (!res.ok || !res.body) {
          reject(new Error(`HTTP ${res.status}`));
          return;
        }
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
            if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
              continue;
            }
            if (line.startsWith("data:")) {
              const data = line.slice(5).trim();
              if (eventType === "result") {
                try {
                  onResult(JSON.parse(data));
                } catch {
                  /* ignore */
                }
              }
              if (eventType === "done") {
                resolve();
                return;
              }
            }
          }
        }
        resolve();
      } catch (e) {
        reject(e);
      }
    });
  },
};
