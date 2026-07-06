"use client";
import { useState, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
import { User as UserIcon, Zap, Ban, X } from "lucide-react";
import type { User, Platform, DiscoverySource } from "@/types";
import toast from "react-hot-toast";
import { SessionConnections } from "./session-connections";
import { PLATFORM_LABELS } from "@/lib/utils";

// Fallback if the sources endpoint is unreachable — browser scrapers only.
const FALLBACK_PLATFORMS: Platform[] = [
  "linkedin", "naukri", "indeed", "wellfound", "hirist", "instahyre",
  "cutshort", "foundit", "iimjobs", "timesjobs", "shine", "freshersworld",
  "glassdoor", "ycombinator", "dice", "ziprecruiter", "weworkremotely",
];

export function SettingsClient({ profile, userId }: { profile: Partial<User>; userId: string }) {
  const [form, setForm] = useState({
    full_name: profile?.full_name || "",
    headline: profile?.headline || "",
    location: profile?.location || "",
    phone: profile?.phone || "",
    experience_years: profile?.experience_years || 0,
    career_goals: profile?.career_goals || "",
    expected_salary_min: profile?.expected_salary_min || "",
    expected_salary_max: profile?.expected_salary_max || "",
    notice_period_days: profile?.notice_period_days || 30,
    work_authorization: profile?.work_authorization || "",
    willing_to_relocate: profile?.willing_to_relocate ?? true,
    skills: (profile?.skills || []).join(", "),
    auto_apply_enabled: profile?.auto_apply_enabled || false,
    auto_apply_threshold: profile?.auto_apply_threshold || 80,
    preferred_platforms: profile?.preferred_platforms || [],
  });
  const [saving, setSaving] = useState(false);
  const [blacklist, setBlacklist] = useState<string[]>([]);
  const [blacklistInput, setBlacklistInput] = useState("");
  const [skillExp, setSkillExp] = useState<Record<string, string>>({});
  const [savingSkills, setSavingSkills] = useState(false);
  const [scraperSources, setScraperSources] = useState<Platform[]>(FALLBACK_PLATFORMS);
  const [apiSources, setApiSources] = useState<DiscoverySource[]>([]);

  const supabase = createClient();

  useEffect(() => {
    api.discovery.sources().then(({ sources }) => {
      // Only discoverable browser scrapers are user-selectable; C-tier boards
      // (hard bot-walls) are display/apply-only and excluded from the picker.
      setScraperSources(sources.filter(s => !s.api_based && s.discoverable).map(s => s.name));
      setApiSources(sources.filter(s => s.api_based && s.discoverable));
    }).catch(() => {});
    api.automation.getBlacklist().then(data => {
      setBlacklist(data.map((d: any) => d.company_name));
    }).catch(() => {});
    api.profile.getSkillExperience().then(data => {
      const exp: Record<string, string> = {};
      Object.entries(data.skill_experience || {}).forEach(([k, v]) => { exp[k] = String(v); });
      setSkillExp(exp);
    }).catch(() => {});
  }, []);

  const saveSkillExperience = async () => {
    setSavingSkills(true);
    try {
      const payload: Record<string, number> = {};
      Object.entries(skillExp).forEach(([k, v]) => { if (v !== "" && v != null) payload[k] = Number(v); });
      await api.profile.saveSkillExperience(payload);
      toast.success("Skill experience saved");
    } catch (e: any) { toast.error(e.message || "Could not save"); }
    finally { setSavingSkills(false); }
  };

  const addToBlacklist = async () => {
    const name = blacklistInput.trim();
    if (!name) return;
    try {
      await api.automation.addToBlacklist(name);
      setBlacklist(b => [...b, name]);
      setBlacklistInput("");
      toast.success(`${name} added to blacklist`);
    } catch (e: any) { toast.error(e.message); }
  };

  const removeFromBlacklist = async (company: string) => {
    try {
      await api.automation.removeFromBlacklist(company);
      setBlacklist(b => b.filter(c => c !== company));
      toast.success(`${company} removed`);
    } catch (e: any) { toast.error(e.message); }
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const skills = form.skills.split(",").map(s => s.trim()).filter(Boolean);
      await supabase.from("users").update({
        full_name: form.full_name,
        headline: form.headline,
        location: form.location,
        phone: form.phone,
        experience_years: Number(form.experience_years),
        career_goals: form.career_goals,
        expected_salary_min: Number(form.expected_salary_min) || null,
        expected_salary_max: Number(form.expected_salary_max) || null,
        notice_period_days: Number(form.notice_period_days),
        skills,
        auto_apply_enabled: form.auto_apply_enabled,
        auto_apply_threshold: Number(form.auto_apply_threshold),
        preferred_platforms: form.preferred_platforms,
      }).eq("id", userId);
      // New application-profile columns go through the resilient backend endpoint
      // (handles pre-migration absence gracefully).
      await api.profile.save({
        work_authorization: form.work_authorization || null,
        willing_to_relocate: form.willing_to_relocate,
      }).catch(() => {});
      toast.success("Settings saved!");
    } catch (e: any) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  const togglePlatform = (p: Platform) => {
    setForm(f => ({
      ...f,
      preferred_platforms: f.preferred_platforms.includes(p)
        ? f.preferred_platforms.filter((x) => x !== p)
        : [...f.preferred_platforms, p],
    }));
  };

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      <form onSubmit={save} className="space-y-6">
        {/* Profile */}
        <div className="card p-6 space-y-4">
          <div className="flex items-center gap-2 mb-2">
            <UserIcon size={16} className="text-amber-400" />
            <h2 className="font-semibold">Profile</h2>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div><label className="label">Full Name</label><input className="input" value={form.full_name} onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))} /></div>
            <div><label className="label">Headline</label><input className="input" value={form.headline} onChange={e => setForm(f => ({ ...f, headline: e.target.value }))} placeholder="Senior React Developer · 5 YOE" /></div>
            <div><label className="label">Location</label><input className="input" value={form.location} onChange={e => setForm(f => ({ ...f, location: e.target.value }))} /></div>
            <div><label className="label">Phone</label><input className="input" value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} placeholder="+91 ..." /></div>
            <div><label className="label">Years of Experience</label><input type="number" min="0" max="50" className="input" value={form.experience_years} onChange={e => setForm(f => ({ ...f, experience_years: +e.target.value }))} /></div>
            <div><label className="label">Expected Salary Min (₹)</label><input type="number" className="input" value={form.expected_salary_min} onChange={e => setForm(f => ({ ...f, expected_salary_min: e.target.value }))} /></div>
            <div><label className="label">Expected Salary Max (₹)</label><input type="number" className="input" value={form.expected_salary_max} onChange={e => setForm(f => ({ ...f, expected_salary_max: e.target.value }))} /></div>
            <div><label className="label">Notice Period (days)</label><input type="number" className="input" value={form.notice_period_days} onChange={e => setForm(f => ({ ...f, notice_period_days: +e.target.value }))} /></div>
            <div>
              <label className="label">Work Authorization</label>
              <select className="input" value={form.work_authorization} onChange={e => setForm(f => ({ ...f, work_authorization: e.target.value }))}>
                <option value="">Select…</option>
                <option value="citizen">Citizen</option>
                <option value="permanent_resident">Permanent Resident</option>
                <option value="work_visa">Work Visa Holder</option>
                <option value="need_sponsorship">Need Sponsorship</option>
                <option value="not_authorized">Not Authorized</option>
              </select>
            </div>
            <div className="flex items-end justify-between">
              <div>
                <p className="text-sm font-medium">Willing to Relocate</p>
                <p className="text-xs text-zinc-500">Used to auto-fill applications</p>
              </div>
              <button type="button" onClick={() => setForm(f => ({ ...f, willing_to_relocate: !f.willing_to_relocate }))}
                className={`w-11 h-6 rounded-full transition-colors ${form.willing_to_relocate ? "bg-amber-500" : "bg-zinc-700"}`}>
                <div className={`w-4 h-4 bg-white rounded-full mx-1 transition-transform ${form.willing_to_relocate ? "translate-x-5" : ""}`} />
              </button>
            </div>
          </div>
          <div><label className="label">Skills (comma separated)</label><textarea className="input" rows={3} value={form.skills} onChange={e => setForm(f => ({ ...f, skills: e.target.value }))} placeholder="React, Node.js, TypeScript, PostgreSQL..." /></div>
          <div><label className="label">Career Goals</label><textarea className="input" rows={2} value={form.career_goals} onChange={e => setForm(f => ({ ...f, career_goals: e.target.value }))} placeholder="I'm looking for a senior frontend role at a product company..." /></div>
        </div>

        {/* Auto-Apply Settings */}
        <div className="card p-6 space-y-4">
          <div className="flex items-center gap-2 mb-2">
            <Zap size={16} className="text-amber-400" />
            <h2 className="font-semibold">Automation</h2>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Enable Auto-Apply</p>
              <p className="text-xs text-zinc-500">Automatically submit applications above your threshold</p>
            </div>
            <button type="button" onClick={() => setForm(f => ({ ...f, auto_apply_enabled: !f.auto_apply_enabled }))}
              className={`w-11 h-6 rounded-full transition-colors ${form.auto_apply_enabled ? "bg-amber-500" : "bg-zinc-700"}`}>
              <div className={`w-4 h-4 bg-white rounded-full mx-1 transition-transform ${form.auto_apply_enabled ? "translate-x-5" : ""}`} />
            </button>
          </div>
          <div>
            <label className="label">Auto-Apply Threshold: <span className="text-amber-400">{form.auto_apply_threshold}%</span></label>
            <input type="range" min="60" max="100" value={form.auto_apply_threshold} onChange={e => setForm(f => ({ ...f, auto_apply_threshold: +e.target.value }))} className="w-full accent-amber-500" />
            <div className="flex justify-between text-xs text-zinc-600"><span>60%</span><span>100%</span></div>
          </div>
          <div>
            <label className="label">Job Board Sources</label>
            <p className="text-xs text-zinc-500 mb-2">
              {form.preferred_platforms.length === 0
                ? "All sources are searched (recommended). Select specific boards to narrow discovery to just those."
                : `Discovery is narrowed to ${form.preferred_platforms.length} selected source${form.preferred_platforms.length > 1 ? "s" : ""} — clear the selection to search everything.`}
            </p>
            <div className="flex flex-wrap gap-2">
              {scraperSources.map(p => (
                <button key={p} type="button" onClick={() => togglePlatform(p)}
                  className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${form.preferred_platforms.includes(p) ? "bg-amber-500/10 border-amber-500/50 text-amber-300" : "border-zinc-700 text-zinc-400 hover:border-zinc-500"}`}>
                  {PLATFORM_LABELS[p] || p}
                </button>
              ))}
            </div>
            {apiSources.length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-zinc-600 mb-1.5">API sources (always on when available):</p>
                <div className="flex flex-wrap gap-2">
                  {apiSources.map(s => (
                    <span key={s.name} title={s.key_configured === false ? "Add the API key in the backend .env to activate" : undefined}
                      className={`text-xs px-3 py-1.5 rounded-full border ${s.key_configured === false ? "border-zinc-800 text-zinc-600 line-through" : "border-emerald-500/30 text-emerald-400/80"}`}>
                      {PLATFORM_LABELS[s.name] || s.name}{s.key_configured === false ? " — no key" : ""}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <button type="submit" disabled={saving} className="btn-primary w-full py-2.5 disabled:opacity-50">
          {saving ? "Saving..." : "Save Settings"}
        </button>
      </form>

      {/* Per-skill experience */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <UserIcon size={16} className="text-amber-400" />
          <h2 className="font-semibold">Experience by Skill</h2>
        </div>
        <p className="text-xs text-zinc-500">
          Set how many years you've worked with each skill. Applications use these exact numbers — they are never guessed.
        </p>
        {(() => {
          const skills = form.skills.split(",").map(s => s.trim()).filter(Boolean);
          if (skills.length === 0) return <p className="text-xs text-zinc-600">Add skills above (and Save Settings) to set per-skill experience.</p>;
          return (
            <div className="grid grid-cols-2 gap-3">
              {skills.map(skill => (
                <div key={skill} className="flex items-center gap-2">
                  <span className="flex-1 text-sm text-zinc-300 truncate" title={skill}>{skill}</span>
                  <input
                    type="number" min="0" max="50"
                    className="input w-20 text-center"
                    placeholder="yrs"
                    value={skillExp[skill] ?? ""}
                    onChange={e => setSkillExp(s => ({ ...s, [skill]: e.target.value }))}
                  />
                </div>
              ))}
            </div>
          );
        })()}
        <button onClick={saveSkillExperience} disabled={savingSkills} className="btn-secondary disabled:opacity-50">
          {savingSkills ? "Saving..." : "Save Skill Experience"}
        </button>
      </div>

      {/* Session-Based Connections */}
      <SessionConnections />

      {/* Company Blacklist */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center gap-2 mb-2">
          <Ban size={16} className="text-amber-400" />
          <h2 className="font-semibold">Company Blacklist</h2>
          <span className="text-xs text-zinc-500">(never auto-apply here)</span>
        </div>
        <div className="flex gap-2">
          <input
            className="input flex-1"
            placeholder="Enter company name..."
            value={blacklistInput}
            onChange={e => setBlacklistInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && addToBlacklist()}
          />
          <button onClick={addToBlacklist} className="btn-secondary px-4">Add</button>
        </div>
        {blacklist.length === 0 ? (
          <p className="text-xs text-zinc-600">No companies blacklisted yet.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {blacklist.map(company => (
              <span key={company} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full bg-red-500/10 border border-red-500/30 text-red-400">
                {company}
                <button onClick={() => removeFromBlacklist(company)} className="hover:text-red-200 transition-colors">
                  <X size={11} />
                </button>
              </span>
            ))}
          </div>
        )}
        <p className="text-xs text-zinc-600">Jobs from blacklisted companies are silently skipped during discovery.</p>
      </div>
    </div>
  );
}
