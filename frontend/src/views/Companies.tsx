import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Company, type DiscoverResult } from "../api/client";

/** Mirrors server ALLOWED_ATS_TYPES + unset for DB null */
const ATS_EDIT_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Unset (auto on scrape)" },
  { value: "greenhouse", label: "greenhouse" },
  { value: "lever", label: "lever" },
  { value: "ashby", label: "ashby" },
  { value: "workday", label: "workday" },
];

function atsSelectOptions(current: string | null): { value: string; label: string }[] {
  const cur = (current || "").trim();
  if (cur && !ATS_EDIT_OPTIONS.some((o) => o.value === cur)) {
    return [{ value: cur, label: `${cur} (current)` }, ...ATS_EDIT_OPTIONS];
  }
  return ATS_EDIT_OPTIONS;
}

function atsOptionLabel(value: string, stored: string | null): string {
  const o = atsSelectOptions(stored).find((x) => x.value === value);
  return o?.label ?? (value || "Unset");
}

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

function CompanyRow({
  c,
  onScraped,
  onNavigateToRun,
}: {
  c: Company;
  onScraped: () => void;
  onNavigateToRun: (runId: number) => void;
}) {
  const [scraping, setScraping] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [editingUrl, setEditingUrl] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [urlSaving, setUrlSaving] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [editingAts, setEditingAts] = useState(false);
  const [atsDraft, setAtsDraft] = useState("");
  const [atsSaving, setAtsSaving] = useState(false);
  const [atsError, setAtsError] = useState<string | null>(null);
  const [atsMenuOpen, setAtsMenuOpen] = useState(false);
  const atsMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!atsMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (atsMenuRef.current && !atsMenuRef.current.contains(e.target as Node)) {
        setAtsMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [atsMenuOpen]);

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

  const startEditUrl = () => {
    setUrlDraft(c.careers_url ?? "");
    setUrlError(null);
    setEditingUrl(true);
  };

  const cancelEditUrl = () => {
    setEditingUrl(false);
    setUrlError(null);
  };

  const saveCareersUrl = async () => {
    setUrlSaving(true);
    setUrlError(null);
    try {
      await api.patchCompany(c.id, { careers_url: urlDraft.trim() });
      setEditingUrl(false);
      onScraped();
    } catch (e: unknown) {
      setUrlError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setUrlSaving(false);
    }
  };

  const startEditAts = () => {
    setAtsDraft((c.ats_type ?? "").trim());
    setAtsError(null);
    setAtsMenuOpen(false);
    setEditingAts(true);
  };

  const cancelEditAts = () => {
    setEditingAts(false);
    setAtsMenuOpen(false);
    setAtsError(null);
  };

  const saveAtsType = async () => {
    setAtsSaving(true);
    setAtsError(null);
    try {
      await api.patchCompany(c.id, { ats_type: atsDraft });
      setEditingAts(false);
      setAtsMenuOpen(false);
      onScraped();
    } catch (e: unknown) {
      setAtsError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setAtsSaving(false);
    }
  };

  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50/80">
      <td className="px-3 py-2 align-top">
        <div className="font-medium text-slate-900">{c.name}</div>
        {c.domain ? (
          <div className="text-xs text-slate-500">{c.domain}</div>
        ) : null}
      </td>
      <td className="px-3 py-2 align-top text-slate-700 min-w-[140px]">
        {editingAts ? (
          <div className="space-y-1.5">
            {/* Native <select> is clipped inside overflow-auto / overflow-hidden tables; use a popover menu. */}
            <div className="relative z-50" ref={atsMenuRef}>
              <button
                type="button"
                disabled={atsSaving}
                onClick={() => setAtsMenuOpen((v) => !v)}
                className="w-full max-w-[220px] flex items-center justify-between gap-1 border border-slate-200 rounded px-2 py-1.5 text-xs bg-white text-left hover:bg-slate-50 disabled:opacity-50"
                aria-expanded={atsMenuOpen}
                aria-haspopup="listbox"
              >
                <span className="truncate">{atsOptionLabel(atsDraft, c.ats_type)}</span>
                <span className="text-slate-400 shrink-0" aria-hidden>
                  {atsMenuOpen ? "▴" : "▾"}
                </span>
              </button>
              {atsMenuOpen ? (
                <ul
                  role="listbox"
                  className="absolute left-0 top-full z-50 mt-0.5 min-w-full max-h-52 overflow-y-auto rounded border border-slate-200 bg-white py-0.5 shadow-lg"
                >
                  {atsSelectOptions(c.ats_type).map((o) => (
                    <li key={o.value || "__unset__"} role="option" aria-selected={atsDraft === o.value}>
                      <button
                        type="button"
                        className={`w-full px-2 py-1.5 text-left text-xs hover:bg-slate-50 ${
                          atsDraft === o.value ? "bg-indigo-50 text-indigo-900 font-medium" : ""
                        }`}
                        onClick={() => {
                          setAtsDraft(o.value);
                          setAtsMenuOpen(false);
                        }}
                      >
                        {o.label}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-1">
              <button
                type="button"
                onClick={saveAtsType}
                disabled={atsSaving}
                className="px-2 py-0.5 text-xs rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {atsSaving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={cancelEditAts}
                disabled={atsSaving}
                className="px-2 py-0.5 text-xs rounded border border-slate-200 text-slate-600 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
            {atsError ? <div className="text-xs text-red-600">{atsError}</div> : null}
          </div>
        ) : (
          <div className="space-y-0.5">
            <div className="whitespace-nowrap">{formatAts(c)}</div>
            <button
              type="button"
              onClick={startEditAts}
              className="text-xs text-indigo-600 hover:underline font-medium"
            >
              Change ATS
            </button>
          </div>
        )}
      </td>
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
      <td className="px-3 py-2 align-top max-w-[min(360px,40vw)]">
        {editingUrl ? (
          <div className="space-y-1.5">
            <input
              type="url"
              value={urlDraft}
              onChange={(e) => setUrlDraft(e.target.value)}
              placeholder="https://… (empty to clear)"
              className="w-full min-w-[200px] border border-slate-200 rounded px-2 py-1 text-xs font-mono"
              disabled={urlSaving}
            />
            <div className="flex flex-wrap gap-1">
              <button
                type="button"
                onClick={saveCareersUrl}
                disabled={urlSaving}
                className="px-2 py-0.5 text-xs rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {urlSaving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={cancelEditUrl}
                disabled={urlSaving}
                className="px-2 py-0.5 text-xs rounded border border-slate-200 text-slate-600 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
            {urlError ? <div className="text-xs text-red-600">{urlError}</div> : null}
          </div>
        ) : (
          <div className="space-y-1">
            {c.careers_url ? (
              <a
                href={c.careers_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-700 hover:underline text-xs block truncate"
                title={c.careers_url}
              >
                {c.careers_url}
              </a>
            ) : (
              <span className="text-xs text-slate-400">No URL stored</span>
            )}
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              {boardHref ? (
                <a
                  href={boardHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-600 hover:underline text-xs"
                >
                  Open board
                </a>
              ) : null}
              <button
                type="button"
                onClick={startEditUrl}
                className="text-xs text-indigo-600 hover:underline font-medium"
              >
                Edit URL
              </button>
            </div>
          </div>
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
  const [addOpen, setAddOpen] = useState(false);
  const [addName, setAddName] = useState("");
  const [addAts, setAddAts] = useState("");
  const [addSlug, setAddSlug] = useState("");
  const [addUrl, setAddUrl] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [addBusy, setAddBusy] = useState(false);
  const [addOk, setAddOk] = useState(false);
  const [addAtsMenuOpen, setAddAtsMenuOpen] = useState(false);
  const addAtsMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!addAtsMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (addAtsMenuRef.current && !addAtsMenuRef.current.contains(e.target as Node)) {
        setAddAtsMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [addAtsMenuOpen]);

  const submitAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddError(null);
    setAddOk(false);
    if (!addName.trim()) {
      setAddError("Name is required");
      return;
    }
    const atsVal = addAts.trim();
    if (["greenhouse", "lever", "ashby"].includes(atsVal) && !addSlug.trim()) {
      setAddError("ATS slug is required for this ATS type");
      return;
    }
    if (atsVal === "workday" && !addUrl.trim()) {
      setAddError("Careers URL is required for this ATS type");
      return;
    }
    const body: Parameters<typeof api.addCompany>[0] = { name: addName.trim() };
    if (atsVal) body.ats_type = atsVal;
    if (addSlug.trim()) body.ats_slug = addSlug.trim();
    if (addUrl.trim()) body.careers_url = addUrl.trim();
    setAddBusy(true);
    try {
      await api.addCompany(body);
      await qc.invalidateQueries({ queryKey: ["companies"] });
      setAddOpen(false);
      setAddName("");
      setAddAts("");
      setAddSlug("");
      setAddUrl("");
      setAddOk(true);
      window.setTimeout(() => setAddOk(false), 4000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.includes("already exists")) {
        setAddError("A company with this name already exists");
      } else {
        setAddError(msg || "Failed to add company");
      }
    } finally {
      setAddBusy(false);
    }
  };

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
        c.careers_url,
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
        <div className="text-sm text-slate-600 pb-1 flex items-center gap-2">
          {isLoading ? "Loading…" : isError ? "Failed to load" : `${filtered.length} / ${companies.length} companies`}
          {addOk ? <span className="text-emerald-600 font-medium">Company added</span> : null}
        </div>
        <button
          type="button"
          onClick={() => {
            setAddError(null);
            setAddName("");
            setAddAts("");
            setAddSlug("");
            setAddUrl("");
            setAddAtsMenuOpen(false);
            setAddOpen(true);
          }}
          className="self-end mb-0.5 px-3 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700"
        >
          Add Company
        </button>
        {false && (
          <button
            onClick={() => setShowDiscover((v) => !v)}
            className="self-end mb-0.5 px-3 py-1.5 text-sm border border-indigo-300 text-indigo-700 rounded hover:bg-indigo-50"
          >
            {showDiscover ? "Hide Discover" : "+ Discover"}
          </button>
        )}
      </header>

      {false && showDiscover && (
        <div className="shrink-0 px-4 py-3 bg-slate-50 border-b border-slate-200">
          <DiscoverPanel onAdded={() => qc.invalidateQueries({ queryKey: ["companies"] })} />
        </div>
      )}

      <div className="flex-1 overflow-auto p-4">
        <div className="bg-white border border-slate-200 rounded-lg shadow-sm">
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
                <th className="px-3 py-2 font-semibold">Careers URL</th>
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

      {addOpen
        ? createPortal(
            <div
              className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/40"
              onClick={() => !addBusy && setAddOpen(false)}
              onKeyDown={(e) => e.key === "Escape" && !addBusy && setAddOpen(false)}
              role="presentation"
            >
              <div
                className="bg-white rounded-lg border border-slate-200 shadow-lg max-w-lg w-full p-5 space-y-4 relative z-[1]"
                role="dialog"
                aria-modal="true"
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
              >
                <div className="font-semibold text-slate-900">Add company</div>
                {addError ? (
                  <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded px-3 py-2">{addError}</div>
                ) : null}
                <form onSubmit={submitAdd} className="space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">Name *</label>
                    <input
                      value={addName}
                      onChange={(e) => setAddName(e.target.value)}
                      className="w-full border border-slate-200 rounded px-2 py-1.5 text-sm"
                      required
                      disabled={addBusy}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">ATS type</label>
                    <div className="relative z-10" ref={addAtsMenuRef}>
                      <button
                        type="button"
                        disabled={addBusy}
                        onClick={() => setAddAtsMenuOpen((v) => !v)}
                        className="w-full flex items-center justify-between gap-1 border border-slate-200 rounded px-2 py-1.5 text-sm bg-white text-left hover:bg-slate-50 disabled:opacity-50"
                        aria-expanded={addAtsMenuOpen}
                        aria-haspopup="listbox"
                      >
                        <span className="truncate">{atsOptionLabel(addAts, addAts)}</span>
                        <span className="text-slate-400 shrink-0" aria-hidden>
                          {addAtsMenuOpen ? "▴" : "▾"}
                        </span>
                      </button>
                      {addAtsMenuOpen ? (
                        <ul
                          role="listbox"
                          className="absolute left-0 right-0 top-full z-[300] mt-0.5 max-h-52 overflow-y-auto rounded border border-slate-200 bg-white py-0.5 shadow-lg"
                        >
                          {ATS_EDIT_OPTIONS.map((o) => (
                            <li key={o.value || "__unset__"} role="option" aria-selected={addAts === o.value}>
                              <button
                                type="button"
                                className={`w-full px-2 py-1.5 text-left text-sm hover:bg-slate-50 ${
                                  addAts === o.value ? "bg-indigo-50 text-indigo-900 font-medium" : ""
                                }`}
                                onClick={() => {
                                  setAddAts(o.value);
                                  setAddAtsMenuOpen(false);
                                }}
                              >
                                {o.label}
                              </button>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">Slug</label>
                    <input
                      value={addSlug}
                      onChange={(e) => setAddSlug(e.target.value)}
                      className="w-full border border-slate-200 rounded px-2 py-1.5 text-sm font-mono"
                      placeholder="e.g. acme"
                      disabled={addBusy}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">Careers URL</label>
                    <input
                      type="url"
                      value={addUrl}
                      onChange={(e) => setAddUrl(e.target.value)}
                      className="w-full border border-slate-200 rounded px-2 py-1.5 text-sm font-mono"
                      placeholder="https://…"
                      disabled={addBusy}
                    />
                  </div>
                  <div className="flex justify-end gap-2 pt-2">
                    <button
                      type="button"
                      onClick={() => !addBusy && setAddOpen(false)}
                      className="px-3 py-1.5 text-sm rounded border border-slate-200 text-slate-700 hover:bg-slate-50"
                      disabled={addBusy}
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={addBusy}
                      className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {addBusy ? "Adding…" : "Add Company"}
                    </button>
                  </div>
                </form>
              </div>
            </div>,
            document.body
          )
        : null}
    </div>
  );
}
