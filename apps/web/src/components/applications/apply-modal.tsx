"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { X, ExternalLink, CheckCircle, AlertTriangle, FileText, Loader2, Sparkles, Wand2, RefreshCw } from "lucide-react";
import toast from "react-hot-toast";

interface ApplyModalProps {
  appId: string;
  jobTitle: string;
  jobCompany: string;
  onClose: () => void;
  onUpdated?: () => void;
}

const FIELD_INPUTS: Record<string, { type: string; placeholder?: string; options?: [string, string][] }> = {
  phone: { type: "text", placeholder: "+91 ..." },
  location: { type: "text", placeholder: "City, Country" },
  expected_salary_min: { type: "number", placeholder: "e.g. 1800000" },
  expected_salary_max: { type: "number", placeholder: "e.g. 2500000" },
  notice_period_days: { type: "number", placeholder: "e.g. 30" },
  experience_years: { type: "number", placeholder: "Total years, e.g. 3" },
  work_authorization: {
    type: "select",
    options: [
      ["citizen", "Citizen"],
      ["permanent_resident", "Permanent Resident"],
      ["work_visa", "Work Visa Holder"],
      ["need_sponsorship", "Need Sponsorship"],
      ["not_authorized", "Not Authorized"],
    ],
  },
};

// Determine the input config for a needs_input field (handles dynamic skill_exp:: / answer:: keys).
function fieldConfig(field: string): { type: string; placeholder?: string; options?: [string, string][] } {
  if (field.startsWith("skill_exp::")) return { type: "number", placeholder: "Years, e.g. 3" };
  if (field.startsWith("answer::")) return { type: "textarea", placeholder: "Your answer (in your own words)" };
  return FIELD_INPUTS[field] || { type: "text" };
}

export function ApplyModal({ appId, jobTitle, jobCompany, onClose, onUpdated }: ApplyModalProps) {
  const [loading, setLoading] = useState(true);
  const [pkg, setPkg] = useState<any>(null);
  const [needsInput, setNeedsInput] = useState<{ field: string; label: string }[] | null>(null);
  const [inputs, setInputs] = useState<Record<string, any>>({});
  const [coverLetter, setCoverLetter] = useState("");
  const [opened, setOpened] = useState(false);
  const [busy, setBusy] = useState(false);
  // User-supplied answers persist across re-prepares (passed as overrides, never re-guessed).
  const [answerOverrides, setAnswerOverrides] = useState<Record<string, any>>({});
  // Per-field AI busy state ("generating" | "rephrasing" | null) keyed by field id.
  const [aiBusy, setAiBusy] = useState<Record<string, "generating" | "rephrasing" | null>>({});
  // Editable copy of pkg.screening_answers so the user can edit / regenerate / rephrase in place.
  const [screeningAnswers, setScreeningAnswers] = useState<{ question: string; answer: string }[]>([]);

  const draftWithAi = async (field: string, question: string) => {
    setAiBusy(s => ({ ...s, [field]: "generating" }));
    try {
      const { answer } = await api.applications.draftAnswer(appId, question);
      setInputs(s => ({ ...s, [field]: answer }));
    } catch (e: any) {
      toast.error(e.message || "Could not generate an answer");
    } finally {
      setAiBusy(s => ({ ...s, [field]: null }));
    }
  };

  const rephraseWithAi = async (field: string, question: string) => {
    const current = (inputs[field] || "").toString().trim();
    if (!current) return;
    setAiBusy(s => ({ ...s, [field]: "rephrasing" }));
    try {
      const { answer } = await api.applications.rephraseAnswer(appId, question, current);
      setInputs(s => ({ ...s, [field]: answer }));
    } catch (e: any) {
      toast.error(e.message || "Could not rephrase");
    } finally {
      setAiBusy(s => ({ ...s, [field]: null }));
    }
  };

  // AI actions for the prepared-state answers (editable in place).
  const regeneratePreparedAnswer = async (i: number, question: string) => {
    const key = `prep::${i}`;
    setAiBusy(s => ({ ...s, [key]: "generating" }));
    try {
      const { answer } = await api.applications.draftAnswer(appId, question);
      setScreeningAnswers(prev => prev.map((qa, idx) => idx === i ? { ...qa, answer } : qa));
    } catch (e: any) {
      toast.error(e.message || "Could not regenerate");
    } finally {
      setAiBusy(s => ({ ...s, [key]: null }));
    }
  };

  const rephrasePreparedAnswer = async (i: number, question: string) => {
    const current = (screeningAnswers[i]?.answer || "").trim();
    if (!current) return;
    const key = `prep::${i}`;
    setAiBusy(s => ({ ...s, [key]: "rephrasing" }));
    try {
      const { answer } = await api.applications.rephraseAnswer(appId, question, current);
      setScreeningAnswers(prev => prev.map((qa, idx) => idx === i ? { ...qa, answer } : qa));
    } catch (e: any) {
      toast.error(e.message || "Could not rephrase");
    } finally {
      setAiBusy(s => ({ ...s, [key]: null }));
    }
  };

  // AI actions for the editable Cover Letter.
  const regenerateCoverLetter = async () => {
    setAiBusy(s => ({ ...s, cover: "generating" }));
    try {
      const { cover_letter } = await api.applications.draftCoverLetter(appId);
      setCoverLetter(cover_letter);
    } catch (e: any) {
      toast.error(e.message || "Could not regenerate cover letter");
    } finally {
      setAiBusy(s => ({ ...s, cover: null }));
    }
  };

  const rephraseCoverLetter = async () => {
    const current = coverLetter.trim();
    if (!current) return;
    setAiBusy(s => ({ ...s, cover: "rephrasing" }));
    try {
      const { cover_letter } = await api.applications.rephraseCoverLetter(appId, current);
      setCoverLetter(cover_letter);
    } catch (e: any) {
      toast.error(e.message || "Could not rephrase cover letter");
    } finally {
      setAiBusy(s => ({ ...s, cover: null }));
    }
  };

  const prepare = useCallback(async (overrides: Record<string, any> = {}) => {
    setLoading(true);
    try {
      const res = await api.applications.prepare(appId, overrides);
      if (res.needs_input) {
        setNeedsInput(res.needs_input);
        setPkg(null);
      } else {
        setNeedsInput(null);
        setPkg(res);
        setCoverLetter(res.cover_letter || "");
        setScreeningAnswers(res.screening_answers || []);
      }
    } catch (e: any) {
      toast.error(e.message || "Failed to prepare application");
    } finally {
      setLoading(false);
    }
  }, [appId]);

  useEffect(() => { prepare(answerOverrides); /* eslint-disable-next-line */ }, [prepare]);

  const saveMissingAndRetry = async () => {
    setBusy(true);
    try {
      // Split: answers are per-application overrides; everything else is profile data.
      const profilePayload: Record<string, any> = {};
      const newAnswers: Record<string, any> = { ...answerOverrides };
      for (const k of Object.keys(inputs)) {
        const v = inputs[k];
        if (v === "" || v == null) continue;
        if (k.startsWith("answer::")) {
          newAnswers[k] = v;
        } else {
          profilePayload[k] = fieldConfig(k).type === "number" ? Number(v) : v;
        }
      }
      if (Object.keys(profilePayload).length > 0) {
        await api.profile.save(profilePayload);
      }
      setAnswerOverrides(newAnswers);
      setInputs({});
      toast.success("Saved — preparing your application");
      await prepare(newAnswers);
    } catch (e: any) {
      toast.error(e.message || "Could not save");
    } finally {
      setBusy(false);
    }
  };

  const openAndApply = async () => {
    const url = pkg?.apply_url;
    if (url) window.open(url, "_blank", "noopener,noreferrer");
    setOpened(true);
    try { await api.applications.markOpened(appId); } catch {}
  };

  const confirmSubmitted = async () => {
    setBusy(true);
    try {
      await api.applications.confirmSubmit(appId);
      toast.success("Application marked as submitted ✓");
      onUpdated?.();
      onClose();
    } catch (e: any) {
      toast.error(e.message || "Failed to update");
    } finally { setBusy(false); }
  };

  const markFailed = async () => {
    const reason = window.prompt("What went wrong? (e.g. role closed, extra questions, login required)");
    if (reason === null) return;
    setBusy(true);
    try {
      await api.applications.markFailed(appId, reason || "Could not submit");
      toast("Marked as failed — you can retry later", { icon: "⚠️" });
      onUpdated?.();
      onClose();
    } catch (e: any) {
      toast.error(e.message || "Failed to update");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-2xl max-h-[88vh] overflow-y-auto rounded-2xl border border-zinc-700 bg-zinc-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-zinc-800 bg-zinc-900 px-6 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-amber-400 text-xs font-mono uppercase tracking-wider mb-1">
              <Sparkles size={13} /> Assisted Apply
            </div>
            <h2 className="text-lg font-bold text-white truncate">{jobTitle}</h2>
            <p className="text-sm text-zinc-400 truncate">{jobCompany}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-zinc-500 hover:text-white hover:bg-zinc-800 transition-colors">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-16 text-zinc-500">
              <Loader2 size={28} className="animate-spin mb-3" />
              <p className="text-sm">Preparing your application — picking resume, writing cover letter, drafting answers…</p>
            </div>
          ) : needsInput ? (
            /* ── Needs input ── */
            <div className="space-y-4">
              <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                <AlertTriangle size={16} className="text-amber-400 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-amber-200">
                  We never guess or auto-fill. Please confirm these real details before we prepare the application — they're saved and reused next time.
                </p>
              </div>
              {needsInput.map((item: any) => {
                const { field, label, hint } = item;
                const cfg = fieldConfig(field);
                const isAnswer = field.startsWith("answer::");
                const question = isAnswer ? field.slice("answer::".length) : "";
                const busyState = aiBusy[field];
                const hasText = !!(inputs[field] || "").toString().trim();
                return (
                  <div key={field}>
                    <label className="label">{label}</label>
                    {hint && <p className="text-xs text-zinc-500 mb-1">Needed: {hint}</p>}
                    {cfg.type === "select" ? (
                      <select className="input" value={inputs[field] || ""} onChange={(e) => setInputs(s => ({ ...s, [field]: e.target.value }))}>
                        <option value="">Select…</option>
                        {cfg.options!.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                    ) : cfg.type === "textarea" ? (
                      <>
                        <textarea
                          className="input"
                          rows={3}
                          placeholder={cfg.placeholder}
                          value={inputs[field] || ""}
                          onChange={(e) => setInputs(s => ({ ...s, [field]: e.target.value }))}
                          disabled={!!busyState}
                        />
                        {isAnswer && (
                          <div className="flex flex-wrap gap-2 mt-2">
                            <button
                              type="button"
                              onClick={() => draftWithAi(field, question)}
                              disabled={!!busyState}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-500/15 text-amber-300 border border-amber-500/30 hover:bg-amber-500/25 transition-colors text-xs font-medium disabled:opacity-50"
                            >
                              {busyState === "generating"
                                ? <><Loader2 size={12} className="animate-spin" /> Generating…</>
                                : <><Wand2 size={12} /> Generate with AI</>}
                            </button>
                            <button
                              type="button"
                              onClick={() => rephraseWithAi(field, question)}
                              disabled={!!busyState || !hasText}
                              title={!hasText ? "Write something first, then I can polish it" : "Improve clarity, grammar and tone"}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-zinc-800 text-zinc-200 border border-zinc-700 hover:bg-zinc-700 transition-colors text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {busyState === "rephrasing"
                                ? <><Loader2 size={12} className="animate-spin" /> Rephrasing…</>
                                : <><RefreshCw size={12} /> Rephrase & Optimize</>}
                            </button>
                          </div>
                        )}
                      </>
                    ) : (
                      <input
                        type={cfg.type}
                        className="input"
                        placeholder={cfg.placeholder}
                        value={inputs[field] || ""}
                        onChange={(e) => setInputs(s => ({ ...s, [field]: e.target.value }))}
                      />
                    )}
                  </div>
                );
              })}
              <button
                onClick={saveMissingAndRetry}
                disabled={busy || Object.values(inputs).every(v => v === "" || v == null)}
                className="btn-primary w-full py-2.5 disabled:opacity-50"
              >
                {busy ? "Saving…" : "Save & Continue"}
              </button>
            </div>
          ) : pkg ? (
            /* ── Ready package ── */
            <div className="space-y-5">
              {/* Resume */}
              <div className="flex items-center gap-3 rounded-lg border border-zinc-700/60 bg-zinc-800/40 px-4 py-3">
                <FileText size={16} className="text-amber-400 flex-shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-zinc-500">Resume to submit</p>
                  <p className="text-sm font-medium text-white truncate">{pkg.resume?.name || "Primary resume"}</p>
                </div>
                {pkg.resume?.file_url && (
                  <a href={pkg.resume.file_url} target="_blank" rel="noopener noreferrer" className="text-xs text-amber-400 hover:underline flex-shrink-0">View</a>
                )}
              </div>

              {/* Cover letter */}
              <div>
                <label className="label">Cover Letter <span className="text-zinc-600">(editable)</span></label>
                <textarea
                  className="input font-sans leading-relaxed"
                  rows={7}
                  value={coverLetter}
                  onChange={(e) => setCoverLetter(e.target.value)}
                  disabled={!!aiBusy.cover}
                />
                <div className="flex flex-wrap gap-2 mt-2">
                  <button
                    type="button"
                    onClick={regenerateCoverLetter}
                    disabled={!!aiBusy.cover}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-500/15 text-amber-300 border border-amber-500/30 hover:bg-amber-500/25 transition-colors text-xs font-medium disabled:opacity-50"
                  >
                    {aiBusy.cover === "generating"
                      ? <><Loader2 size={12} className="animate-spin" /> Generating…</>
                      : <><Wand2 size={12} /> Regenerate with AI</>}
                  </button>
                  <button
                    type="button"
                    onClick={rephraseCoverLetter}
                    disabled={!!aiBusy.cover || !coverLetter.trim()}
                    title={!coverLetter.trim() ? "Write something first, then I can polish it" : "Improve clarity, grammar and tone"}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-zinc-800 text-zinc-200 border border-zinc-700 hover:bg-zinc-700 transition-colors text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {aiBusy.cover === "rephrasing"
                      ? <><Loader2 size={12} className="animate-spin" /> Rephrasing…</>
                      : <><RefreshCw size={12} /> Rephrase & Optimize</>}
                  </button>
                </div>
              </div>

              {/* Drafted screening answers — editable, with AI regenerate / rephrase per answer */}
              {screeningAnswers.length > 0 && (
                <div>
                  <p className="label">Drafted Screening Answers <span className="text-zinc-600">(editable)</span></p>
                  <div className="space-y-2">
                    {screeningAnswers.map((qa, i) => {
                      const key = `prep::${i}`;
                      const busyState = aiBusy[key];
                      const hasText = !!(qa.answer || "").trim();
                      return (
                        <details key={i} open className="rounded-lg border border-zinc-700/60 bg-zinc-800/40 px-4 py-2.5">
                          <summary className="text-sm text-zinc-300 cursor-pointer">{qa.question}</summary>
                          <textarea
                            className="input mt-2 font-sans leading-relaxed"
                            rows={4}
                            value={qa.answer || ""}
                            onChange={(e) => {
                              const v = e.target.value;
                              setScreeningAnswers(prev => prev.map((x, idx) => idx === i ? { ...x, answer: v } : x));
                            }}
                            disabled={!!busyState}
                          />
                          <div className="flex flex-wrap gap-2 mt-2">
                            <button
                              type="button"
                              onClick={() => regeneratePreparedAnswer(i, qa.question)}
                              disabled={!!busyState}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-500/15 text-amber-300 border border-amber-500/30 hover:bg-amber-500/25 transition-colors text-xs font-medium disabled:opacity-50"
                            >
                              {busyState === "generating"
                                ? <><Loader2 size={12} className="animate-spin" /> Generating…</>
                                : <><Wand2 size={12} /> Regenerate with AI</>}
                            </button>
                            <button
                              type="button"
                              onClick={() => rephrasePreparedAnswer(i, qa.question)}
                              disabled={!!busyState || !hasText}
                              title={!hasText ? "Write something first, then I can polish it" : "Improve clarity, grammar and tone"}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-zinc-800 text-zinc-200 border border-zinc-700 hover:bg-zinc-700 transition-colors text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {busyState === "rephrasing"
                                ? <><Loader2 size={12} className="animate-spin" /> Rephrasing…</>
                                : <><RefreshCw size={12} /> Rephrase & Optimize</>}
                            </button>
                          </div>
                        </details>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Form data preview — exactly what will be submitted, from your real profile */}
              <div>
                <p className="label">Information that will be submitted</p>
                <div className="grid grid-cols-2 gap-2 rounded-lg border border-zinc-700/60 bg-zinc-800/40 p-3 text-xs">
                  {Object.entries(pkg.form_data || {})
                    .filter(([k, v]) => k !== "skill_experience" && v !== null && v !== "")
                    .map(([k, v]) => (
                      <div key={k} className="flex gap-1.5">
                        <span className="text-zinc-500 capitalize">{k.replace(/_/g, " ")}:</span>
                        <span className="text-zinc-300 truncate">{String(v)}</span>
                      </div>
                    ))}
                </div>
                {/* Per-skill experience */}
                {pkg.form_data?.skill_experience && Object.keys(pkg.form_data.skill_experience).length > 0 && (
                  <div className="mt-2">
                    <p className="text-xs text-zinc-500 mb-1.5">Experience by skill</p>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(pkg.form_data.skill_experience).map(([skill, yrs]) => (
                        <span key={skill} className="text-xs px-2 py-1 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-300">
                          {skill}: <span className="text-amber-400 font-medium">{String(yrs)}y</span>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                <p className="text-[11px] text-zinc-600 mt-2">
                  All values come from your profile. To change them, edit your profile in Settings — nothing here is auto-generated.
                </p>
              </div>

              {/* Actions */}
              <div className="space-y-2 border-t border-zinc-800 pt-4">
                <button
                  onClick={openAndApply}
                  className="btn-primary w-full py-2.5 flex items-center justify-center gap-2"
                >
                  <ExternalLink size={15} /> Open & Apply on {jobCompany}'s site
                </button>
                {opened && (
                  <div className="grid grid-cols-2 gap-2 pt-1">
                    <button onClick={confirmSubmitted} disabled={busy}
                      className="flex items-center justify-center gap-2 py-2.5 rounded-lg bg-green-500/15 text-green-400 border border-green-500/30 hover:bg-green-500/25 transition-colors text-sm font-medium disabled:opacity-50">
                      <CheckCircle size={15} /> I submitted it
                    </button>
                    <button onClick={markFailed} disabled={busy}
                      className="flex items-center justify-center gap-2 py-2.5 rounded-lg bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25 transition-colors text-sm font-medium disabled:opacity-50">
                      <AlertTriangle size={15} /> It didn't work
                    </button>
                  </div>
                )}
                <p className="text-xs text-zinc-600 text-center pt-1">
                  We open the company's real application page. Confirm once you've submitted so we can track it.
                </p>
              </div>
            </div>
          ) : (
            <div className="py-12 text-center text-zinc-500 text-sm">Couldn't prepare this application.</div>
          )}
        </div>
      </div>
    </div>
  );
}
