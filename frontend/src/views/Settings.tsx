import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type RuntimeSettingsPatch, type SearchProfile } from "../api/client";

const WORK_MODES = ["remote", "hybrid", "onsite"] as const;
const COMPANY_TYPES = ["product", "service"] as const;

function linesToList(text: string): string[] {
  return text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function Settings() {
  const qc = useQueryClient();
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const profileQ = useQuery({ queryKey: ["profile"], queryFn: api.getProfile });
  const settingsQ = useQuery({ queryKey: ["runtime-settings"], queryFn: api.getRuntimeSettings });
  const resumeQ = useQuery({ queryKey: ["resume-info"], queryFn: api.getResumeInfo });

  const [skillsText, setSkillsText] = useState("");
  const [locationsText, setLocationsText] = useState("");
  const [excludeText, setExcludeText] = useState("");
  const [salaryMin, setSalaryMin] = useState(0);
  const [noticeDays, setNoticeDays] = useState(0);
  const [workMode, setWorkMode] = useState<Record<string, boolean>>({});
  const [companyType, setCompanyType] = useState<Record<string, boolean>>({});
  const [resumeSummary, setResumeSummary] = useState("");

  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [scoringModel, setScoringModel] = useState("");
  const [discoverModel, setDiscoverModel] = useState("");
  const [embedBaseUrl, setEmbedBaseUrl] = useState("");
  const [embedModel, setEmbedModel] = useState("");
  const [freshnessHours, setFreshnessHours] = useState(24);
  const [proxyUrl, setProxyUrl] = useState("");
  const [llmKey, setLlmKey] = useState("");
  const [embedKey, setEmbedKey] = useState("");
  const [braveKey, setBraveKey] = useState("");

  useEffect(() => {
    const p = profileQ.data;
    if (!p) return;
    setSkillsText(p.skills.join("\n"));
    setLocationsText(p.locations.join("\n"));
    setExcludeText(p.exclude_companies.join("\n"));
    setSalaryMin(p.salary_min_lpa);
    setNoticeDays(p.notice_days);
    setResumeSummary(p.resume_summary);
    const wm: Record<string, boolean> = {};
    for (const m of WORK_MODES) wm[m] = p.work_mode.includes(m);
    setWorkMode(wm);
    const ct: Record<string, boolean> = {};
    for (const c of COMPANY_TYPES) ct[c] = p.company_type.includes(c);
    setCompanyType(ct);
  }, [profileQ.data]);

  useEffect(() => {
    const s = settingsQ.data;
    if (!s) return;
    setLlmBaseUrl(s.llm_base_url);
    setScoringModel(s.scoring_model);
    setDiscoverModel(s.discover_model);
    setEmbedBaseUrl(s.embed_base_url);
    setEmbedModel(s.embed_model);
    setFreshnessHours(s.scraper_freshness_hours);
    setProxyUrl(s.proxy_url);
    setLlmKey("");
    setEmbedKey("");
    setBraveKey("");
  }, [settingsQ.data]);

  const saveProfile = useMutation({
    mutationFn: (body: SearchProfile) => api.putProfile(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile"] });
      setBanner({ kind: "ok", text: "Profile saved to search_profile.yaml" });
    },
    onError: (e: Error) => setBanner({ kind: "err", text: e.message }),
  });

  const saveSettings = useMutation({
    mutationFn: (patch: RuntimeSettingsPatch) => api.patchRuntimeSettings(patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runtime-settings"] });
      setBanner({ kind: "ok", text: "Settings saved to .env and applied to this server process" });
      setLlmKey("");
      setEmbedKey("");
      setBraveKey("");
    },
    onError: (e: Error) => setBanner({ kind: "err", text: e.message }),
  });

  const uploadResume = useMutation({
    mutationFn: (file: File) => api.uploadResume(file),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["resume-info"] });
      setBanner({ kind: "ok", text: `Resume uploaded (${data.bytes} bytes) → ${data.path}` });
    },
    onError: (e: Error) => setBanner({ kind: "err", text: e.message }),
  });

  const onSubmitProfile = (e: React.FormEvent) => {
    e.preventDefault();
    const body: SearchProfile = {
      skills: linesToList(skillsText),
      locations: linesToList(locationsText),
      salary_min_lpa: salaryMin,
      work_mode: WORK_MODES.filter((m) => workMode[m]),
      company_type: COMPANY_TYPES.filter((c) => companyType[c]),
      exclude_companies: linesToList(excludeText),
      notice_days: noticeDays,
      resume_summary: resumeSummary,
    };
    saveProfile.mutate(body);
  };

  const onSubmitSettings = (e: React.FormEvent) => {
    e.preventDefault();
    const patch: RuntimeSettingsPatch = {
      llm_base_url: llmBaseUrl,
      scoring_model: scoringModel,
      discover_model: discoverModel,
      embed_base_url: embedBaseUrl,
      embed_model: embedModel,
      scraper_freshness_hours: freshnessHours,
      proxy_url: proxyUrl,
    };
    if (llmKey.trim()) patch.llm_api_key = llmKey.trim();
    if (embedKey.trim()) patch.embed_api_key = embedKey.trim();
    if (braveKey.trim()) patch.brave_search_api_key = braveKey.trim();
    saveSettings.mutate(patch);
  };

  const loading = profileQ.isLoading || settingsQ.isLoading;
  const showForms = !loading && profileQ.isSuccess && settingsQ.isSuccess;

  return (
    <div className="h-full overflow-y-auto bg-slate-50 p-4">
      <div className="max-w-3xl mx-auto space-y-6">
        <h1 className="text-xl font-semibold text-slate-900">Profile &amp; settings</h1>
        <p className="text-sm text-slate-600">
          Edit your search profile and LLM configuration. Secrets are written to <code className="text-xs bg-slate-200 px-1 rounded">.env</code> on the
          server; leave key fields blank to keep the current value.
        </p>

        {banner && (
          <div
            className={`text-sm px-3 py-2 rounded border ${
              banner.kind === "ok"
                ? "bg-emerald-50 border-emerald-200 text-emerald-900"
                : "bg-red-50 border-red-200 text-red-900"
            }`}
          >
            {banner.text}
            <button type="button" className="ml-2 underline text-xs" onClick={() => setBanner(null)}>
              dismiss
            </button>
          </div>
        )}

        {!loading && profileQ.isError && (
          <div className="text-sm px-3 py-2 rounded border bg-amber-50 border-amber-200 text-amber-950">
            Profile: {(profileQ.error as Error).message}
          </div>
        )}
        {!loading && settingsQ.isError && (
          <div className="text-sm px-3 py-2 rounded border bg-amber-50 border-amber-200 text-amber-950">
            Settings: {(settingsQ.error as Error).message}
          </div>
        )}

        {loading ? (
          <div className="text-slate-600">Loading…</div>
        ) : showForms ? (
          <>
            <form onSubmit={onSubmitProfile} className="bg-white border border-slate-200 rounded-lg p-4 space-y-4 shadow-sm">
              <h2 className="font-semibold text-slate-800">Job context &amp; resume summary</h2>
              <p className="text-xs text-slate-500">
                This maps to <code className="bg-slate-100 px-1 rounded">search_profile.yaml</code>. The resume summary is the main signal for LLM scoring; keep it dense and factual.
              </p>

              <div>
                <label className="text-sm font-medium block mb-1">Skills (one per line)</label>
                <textarea
                  className="w-full border border-slate-200 rounded p-2 text-sm font-mono min-h-[120px]"
                  value={skillsText}
                  onChange={(e) => setSkillsText(e.target.value)}
                />
              </div>
              <div>
                <label className="text-sm font-medium block mb-1">Locations (one per line)</label>
                <textarea
                  className="w-full border border-slate-200 rounded p-2 text-sm font-mono min-h-[72px]"
                  value={locationsText}
                  onChange={(e) => setLocationsText(e.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-sm font-medium block mb-1">Min salary (LPA)</label>
                  <input
                    type="number"
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={salaryMin}
                    min={0}
                    onChange={(e) => setSalaryMin(parseInt(e.target.value, 10) || 0)}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium block mb-1">Notice period (days)</label>
                  <input
                    type="number"
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={noticeDays}
                    min={0}
                    onChange={(e) => setNoticeDays(parseInt(e.target.value, 10) || 0)}
                  />
                </div>
              </div>

              <div>
                <div className="text-sm font-medium mb-1">Work modes you accept</div>
                <div className="flex flex-wrap gap-3">
                  {WORK_MODES.map((m) => (
                    <label key={m} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={workMode[m] ?? false}
                        onChange={(e) => setWorkMode({ ...workMode, [m]: e.target.checked })}
                      />
                      {m}
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <div className="text-sm font-medium mb-1">Company types</div>
                <div className="flex flex-wrap gap-3">
                  {COMPANY_TYPES.map((c) => (
                    <label key={c} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={companyType[c] ?? false}
                        onChange={(e) => setCompanyType({ ...companyType, [c]: e.target.checked })}
                      />
                      {c}
                    </label>
                  ))}
                </div>
                <p className="text-xs text-slate-500 mt-1">Product-only search: check only product (pipeline drops service companies).</p>
              </div>

              <div>
                <label className="text-sm font-medium block mb-1">Exclude companies (one per line)</label>
                <textarea
                  className="w-full border border-slate-200 rounded p-2 text-sm font-mono min-h-[56px]"
                  value={excludeText}
                  onChange={(e) => setExcludeText(e.target.value)}
                />
              </div>

              <div>
                <label className="text-sm font-medium block mb-1">Resume summary (plain text for the scorer)</label>
                <textarea
                  className="w-full border border-slate-200 rounded p-2 text-sm min-h-[200px]"
                  value={resumeSummary}
                  onChange={(e) => setResumeSummary(e.target.value)}
                />
              </div>

              <div className="border-t border-slate-100 pt-3">
                <div className="text-sm font-medium mb-1">Resume PDF</div>
                <p className="text-xs text-slate-500 mb-2">
                  Stored at <code className="bg-slate-100 px-1 rounded">{resumeQ.data?.path ?? "resume.pdf"}</code>
                  {resumeQ.data?.has_pdf ? " (file on server)" : " — not uploaded yet"}
                </p>
                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  className="text-sm"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) uploadResume.mutate(f);
                    e.target.value = "";
                  }}
                />
              </div>

              <button
                type="submit"
                disabled={saveProfile.isPending}
                className="px-4 py-2 rounded bg-slate-900 text-white text-sm disabled:opacity-50"
              >
                {saveProfile.isPending ? "Saving…" : "Save profile"}
              </button>
            </form>

            <form onSubmit={onSubmitSettings} className="bg-white border border-slate-200 rounded-lg p-4 space-y-4 shadow-sm">
              <h2 className="font-semibold text-slate-800">LLM &amp; API keys</h2>
              <p className="text-xs text-slate-500">
                OpenAI-compatible scoring uses <code className="bg-slate-100 px-1 rounded">LLM_BASE_URL</code> + <code className="bg-slate-100 px-1 rounded">LLM_API_KEY</code>.
                Embeddings use OpenRouter-style settings by default.
              </p>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <label className="text-sm font-medium block mb-1">LLM base URL</label>
                  <input
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={llmBaseUrl}
                    onChange={(e) => setLlmBaseUrl(e.target.value)}
                    placeholder="https://…"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium block mb-1">Scoring model</label>
                  <input
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={scoringModel}
                    onChange={(e) => setScoringModel(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium block mb-1">Discover model (company URLs)</label>
                  <input
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={discoverModel}
                    onChange={(e) => setDiscoverModel(e.target.value)}
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="text-sm font-medium block mb-1">LLM API key</label>
                  <input
                    type="password"
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={llmKey}
                    onChange={(e) => setLlmKey(e.target.value)}
                    placeholder={settingsQ.data?.llm_api_key_set ? `Leave blank (current ${settingsQ.data.llm_api_key_hint})` : "Required for scoring / discover"}
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="text-sm font-medium block mb-1">Embed base URL</label>
                  <input
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={embedBaseUrl}
                    onChange={(e) => setEmbedBaseUrl(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium block mb-1">Embed model</label>
                  <input
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={embedModel}
                    onChange={(e) => setEmbedModel(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium block mb-1">Embed API key</label>
                  <input
                    type="password"
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={embedKey}
                    onChange={(e) => setEmbedKey(e.target.value)}
                    placeholder={settingsQ.data?.embed_api_key_set ? `Leave blank (current ${settingsQ.data.embed_api_key_hint})` : "Optional; defaults to LLM key"}
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="text-sm font-medium block mb-1">Brave Search API key (optional)</label>
                  <input
                    type="password"
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={braveKey}
                    onChange={(e) => setBraveKey(e.target.value)}
                    placeholder={
                      settingsQ.data?.brave_search_api_key_set
                        ? `Leave blank (current ${settingsQ.data.brave_search_api_key_hint})`
                        : "Optional for discover"
                    }
                  />
                </div>
                <div>
                  <label className="text-sm font-medium block mb-1">Scraper freshness (hours)</label>
                  <input
                    type="number"
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={freshnessHours}
                    min={1}
                    onChange={(e) => setFreshnessHours(parseInt(e.target.value, 10) || 24)}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium block mb-1">Proxy URL (optional)</label>
                  <input
                    className="w-full border border-slate-200 rounded p-2 text-sm"
                    value={proxyUrl}
                    onChange={(e) => setProxyUrl(e.target.value)}
                    placeholder="http://…"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={saveSettings.isPending}
                className="px-4 py-2 rounded bg-slate-900 text-white text-sm disabled:opacity-50"
              >
                {saveSettings.isPending ? "Saving…" : "Save LLM settings"}
              </button>
            </form>
          </>
        ) : (
          <div className="text-sm text-slate-600">Fix the errors above or start the API, then refresh.</div>
        )}
      </div>
    </div>
  );
}
