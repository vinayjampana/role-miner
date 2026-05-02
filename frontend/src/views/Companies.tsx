import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Company, type DiscoverResult } from "../api/client";

function formatAts(c: Company): string {
  const t = c.ats_type || "—";
  const slug = c.ats_slug ? ` · ${c.ats_slug}` : "";
  return `${t}${slug}`;
}

/** Public job board URL: DB only stores careers_url for Workday; GH/Lever/Ashby use slug + known paths. */
function careersBoardUrl(c: Company): string | null {
  if (c.careers_url) return c.careers_url;
  const slug = c.ats_slug?.trim();
  if (!slug) return null;
  switch (c.ats_type) {
    case "greenhouse":
      return `https://boards.greenhouse.io/${encodeURIComponent(slug)}`;
    case "lever":
      return `https://jobs.lever.co/${encodeURIComponent(slug)}`;
    case "ashby":
      return `https://jobs.ashbyhq.com/${encodeURIComponent(slug)}`;
    default:
      return null;
  }
}

const METHOD_BADGE: Record<string, string> = {
  cache: "bg-slate-100 text-slate-600",
  heuristic: "bg-blue-100 text-blue-700",
  search: "bg-purple-100 text-purple-700",
  llm: "bg-amber-100 text-amber-700",
  failed: "bg-red-100 text-red-600",
};

function DiscoverPanel({ onAdded }: { onAdded: () => void }) {
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<DiscoverResult[]>([]);

  const run = async () => {
    const names = input.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!names.length) return;
    setResults([]);
    setRunning(true);
    try {
      await api.discoverCompanies(names, (r) => {
        setResults((prev) => [...prev, r]);
      });
      onAdded();
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
      <div className="font-semibold text-sm">Discover company career URLs</div>
      <div className="text-xs text-slate-500">
        One company name per line. Resolves via: DB cache → URL heuristics → Brave Search → LLM ({`tencent/hy3-preview`}).
      </div>
      <div className="flex gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={"Setu\nFi Money\nJar\nPerfios"}
          rows={4}
          className="flex-1 border border-slate-200 rounded px-2 py-1.5 text-sm font-mono resize-y"
        />
        <button
          onClick={run}
          disabled={running || !input.trim()}
          className="self-start px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50 whitespace-nowrap"
        >
          {running ? "Discovering…" : "Discover"}
        </button>
      </div>

      {results.length > 0 && (
        <div className="border border-slate-100 rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500 uppercase">
              <tr>
                <th className="px-3 py-2 text-left">Company</th>
                <th className="px-3 py-2 text-left">ATS</th>
                <th className="px-3 py-2 text-left">Careers URL</th>
                <th className="px-3 py-2 text-left">Method</th>
                <th className="px-3 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {results.map((r, i) => (
                <tr key={i} className={r.found ? "" : "opacity-50"}>
                  <td className="px-3 py-2 font-medium">{r.name}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {r.ats_type ?? "—"}
                    {r.ats_slug ? <span className="ml-1 text-slate-400">· {r.ats_slug}</span> : null}
                  </td>
                  <td className="px-3 py-2 max-w-[260px]">
                    {r.careers_url ? (
                      <a href={r.careers_url} target="_blank" rel="noopener noreferrer"
                        className="text-sky-700 hover:underline text-xs truncate block">
                        {r.careers_url}
                      </a>
                    ) : <span className="text-slate-400 text-xs">not found</span>}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${METHOD_BADGE[r.method] ?? ""}`}>
                      {r.method}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {r.already_in_db
                      ? <span className="text-slate-400">updated</span>
                      : r.found
                      ? <span className="text-emerald-600 font-medium">added</span>
                      : <span className="text-red-500">failed</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CompanyRow({ c, onScraped, onNavigateToRun }: { c: Company; onScraped: () => void; onNavigateToRun: (runId: number) => void }) {
  const [scraping, setScraping] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const run = async () => {
    setScraping(true);
    setResult(null);
    try {
      const res = await api.scrapeCompany(c.id);
      onScraped();
      if (res.run_id) {
        onNavigateToRun(res.run_id);
      }
    } catch (e: any) {
      setResult(e.message || "Unknown error");
    } finally {
      setScraping(false);
    }
  };

  const boardHref = careersBoardUrl(c);

  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50/80">
      <td className="px-3 py-2 align-top">
        <div className="font-medium text-slate-900">{c.name}</div>
        {c.domain ? (
          <div className="text-xs text-slate-500">{c.domain}</div>
        ) : null}
      </td>
      <td className="px-3 py-2 align-top text-slate-700 whitespace-nowrap">{formatAts(c)}</td>
      <td className="px-3 py-2 align-top text-slate-700">{c.hq_city || "—"}</td>
      <td className="px-3 py-2 align-top text-slate-700">{c.company_type || "—"}</td>
      <td className="px-3 py-2 align-top text-slate-700">{c.funding_stage || "—"}</td>
      <td className="px-3 py-2 align-top max-w-[220px]">
        {c.tech_stack?.length ? (
          <div className="flex flex-wrap gap-1">
            {c.tech_stack.slice(0, 6).map((t) => (
              <span
                key={t}
                className="inline-block text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-700"
              >
                {t}
              </span>
            ))}
            {c.tech_stack.length > 6 ? (
              <span className="text-xs text-slate-500">+{c.tech_stack.length - 6}</span>
            ) : null}
          </div>
        ) : (
          "—"
        )}
      </td>
      <td className="px-3 py-2 align-top text-slate-600 text-xs whitespace-nowrap">
        {c.last_scraped_at
          ? new Date(c.last_scraped_at).toLocaleString(undefined, {
              dateStyle: "short",
              timeStyle: "short",
            })
          : "—"}
      </td>
      <td className="px-3 py-2 align-top">
        {boardHref ? (
          <a
            href={boardHref}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sky-700 hover:underline text-xs"
          >
            Open
          </a>
        ) : (
          "—"
        )}
      </td>
      <td className="px-3 py-2 align-top">
        <button
          onClick={run}
          disabled={scraping}
          className="px-2 py-1 text-xs rounded border border-emerald-300 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {scraping ? "Running…" : "Run"}
        </button>
        {result && (
          <div className="text-xs text-red-500 mt-0.5">{result}</div>
        )}
      </td>
    </tr>
  );
}

export function Companies({ onNavigateToRun }: { onNavigateToRun: (runId: number) => void }) {
  const qc = useQueryClient();
  const { data: companies = [], isLoading, isError } = useQuery({
    queryKey: ["companies"],
    queryFn: api.companies,
  });

  const [q, setQ] = useState("");
  const [ats, setAts] = useState<string>("");
  const [showDiscover, setShowDiscover] = useState(false);

  const atsOptions = useMemo(() => {
    const s = new Set<string>();
    for (const c of companies) {
      if (c.ats_type) s.add(c.ats_type);
    }
    return Array.from(s).sort();
  }, [companies]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return companies.filter((c) => {
      if (ats && c.ats_type !== ats) return false;
      if (!needle) return true;
      const blob = [
        c.name,
        c.domain,
        c.ats_slug,
        c.hq_city,
        c.company_type,
        c.funding_stage,
        ...(c.tech_stack || []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return blob.includes(needle);
    });
  }, [companies, q, ats]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <header className="shrink-0 bg-white border-b border-slate-200 px-4 py-3 flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs font-medium text-slate-500 block mb-1">Search</label>
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Name, domain, city, stack…"
            className="w-full border border-slate-200 rounded px-2 py-1.5 text-sm"
          />
        </div>
        <div className="w-44">
          <label className="text-xs font-medium text-slate-500 block mb-1">ATS</label>
          <select
            value={ats}
            onChange={(e) => setAts(e.target.value)}
            className="w-full border border-slate-200 rounded px-2 py-1.5 text-sm bg-white"
          >
            <option value="">All</option>
            {atsOptions.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
        <div className="text-sm text-slate-600 pb-1">
          {isLoading ? "Loading…" : isError ? "Failed to load" : `${filtered.length} / ${companies.length} companies`}
        </div>
        <button
          onClick={() => setShowDiscover((v) => !v)}
          className="self-end mb-0.5 px-3 py-1.5 text-sm border border-indigo-300 text-indigo-700 rounded hover:bg-indigo-50"
        >
          {showDiscover ? "Hide Discover" : "+ Discover"}
        </button>
      </header>

      {showDiscover && (
        <div className="shrink-0 px-4 py-3 bg-slate-50 border-b border-slate-200">
          <DiscoverPanel onAdded={() => qc.invalidateQueries({ queryKey: ["companies"] })} />
        </div>
      )}

      <div className="flex-1 overflow-auto p-4">
        <div className="bg-white border border-slate-200 rounded-lg overflow-hidden shadow-sm">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-slate-50 text-left text-slate-600 border-b border-slate-200">
                <th className="px-3 py-2 font-semibold">Company</th>
                <th className="px-3 py-2 font-semibold">ATS</th>
                <th className="px-3 py-2 font-semibold">HQ</th>
                <th className="px-3 py-2 font-semibold">Type</th>
                <th className="px-3 py-2 font-semibold">Funding</th>
                <th className="px-3 py-2 font-semibold">Tech stack</th>
                <th className="px-3 py-2 font-semibold">Last scraped</th>
                <th className="px-3 py-2 font-semibold">Careers</th>
                <th className="px-3 py-2 font-semibold">Scrape</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <CompanyRow key={c.id} c={c} onScraped={() => qc.invalidateQueries({ queryKey: ["companies"] })} onNavigateToRun={onNavigateToRun} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
