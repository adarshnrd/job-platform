"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { SavedAnswer, PendingQuestion } from "@/types";
import { cn } from "@/lib/utils";
import {
  Search, Plus, Trash2, Pencil, Check, X, HelpCircle, Lock, Building2,
} from "lucide-react";
import toast from "react-hot-toast";

const CATEGORY_LABELS: Record<string, string> = {
  salary: "Salary", notice_period: "Notice Period", work_auth: "Work Authorization",
  relocation: "Relocation", experience: "Experience", skill_experience: "Skill Experience",
  education: "Education", certification: "Certification", availability: "Availability",
  essay: "Essay", custom: "Custom",
};

export function AnswersClient() {
  const [answers, setAnswers] = useState<SavedAnswer[]>([]);
  const [pending, setPending] = useState<PendingQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [adding, setAdding] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [a, p] = await Promise.all([api.answers.list(), api.answers.pending()]);
      setAnswers(a.answers || []);
      setPending(p.pending || []);
    } catch (e: any) {
      toast.error(e.message || "Failed to load answers");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const filtered = answers.filter(a => {
    const q = search.toLowerCase();
    const matchSearch = !q || a.question_text.toLowerCase().includes(q) || (a.answer || "").toLowerCase().includes(q);
    const matchCat = !category || a.category === category;
    return matchSearch && matchCat;
  });

  const categories = Array.from(new Set(answers.map(a => a.category))).sort();

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold">Answer Bank</h1>
        <p className="text-sm text-zinc-400 mt-0.5">
          Answers you save here auto-fill application questions across every portal — answer once, reuse forever.
        </p>
      </div>

      {pending.length > 0 && (
        <PendingInbox pending={pending} onResolved={load} />
      )}

      {/* Toolbar */}
      <div className="flex gap-3 flex-wrap items-center">
        <div className="relative flex-1 min-w-64">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search questions or answers..." className="input pl-9" />
        </div>
        <select value={category} onChange={e => setCategory(e.target.value)} className="input w-auto">
          <option value="">All categories</option>
          {categories.map(c => <option key={c} value={c}>{CATEGORY_LABELS[c] || c}</option>)}
        </select>
        <button onClick={() => setAdding(true)} className="btn-primary text-xs py-2 flex items-center gap-1">
          <Plus size={14} /> Add answer
        </button>
      </div>

      {adding && <AddAnswerRow onCancel={() => setAdding(false)} onSaved={() => { setAdding(false); load(); }} />}

      {/* Saved answers */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => <div key={i} className="card h-16 animate-pulse bg-zinc-800/40" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card p-10 text-center text-zinc-500">
          <HelpCircle className="mx-auto mb-3 text-zinc-600" size={28} />
          No saved answers yet. They'll appear here as applications ask questions, or add one manually.
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map(a => (
            <div key={a.id} className="card p-4 flex items-start gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400">
                    {CATEGORY_LABELS[a.category] || a.category}
                  </span>
                  {a.is_profile_mapped && (
                    <span title="Answered from your profile — edit it in Settings" className="text-xs px-2 py-0.5 rounded-full bg-blue-900/30 text-blue-300 border border-blue-800/50 flex items-center gap-1">
                      <Lock size={10} /> Profile
                    </span>
                  )}
                  {a.times_used > 0 && (
                    <span className="text-xs text-zinc-600">used {a.times_used}×</span>
                  )}
                </div>
                <p className="text-sm font-medium text-zinc-200">{a.question_text}</p>
                {editingId === a.id ? (
                  <div className="flex items-center gap-2 mt-2">
                    <input value={editValue} onChange={e => setEditValue(e.target.value)} className="input flex-1" autoFocus />
                    <button onClick={async () => {
                      try { await api.answers.update(a.id, editValue); toast.success("Updated"); setEditingId(null); load(); }
                      catch (e: any) { toast.error(e.message); }
                    }} className="p-1.5 rounded text-green-400 hover:bg-zinc-800"><Check size={15} /></button>
                    <button onClick={() => setEditingId(null)} className="p-1.5 rounded text-zinc-400 hover:bg-zinc-800"><X size={15} /></button>
                  </div>
                ) : (
                  <p className={cn("text-sm mt-1", a.answer ? "text-zinc-400" : "text-amber-400 italic")}>
                    {a.answer || "No answer saved yet"}
                  </p>
                )}
              </div>
              {!a.is_profile_mapped && editingId !== a.id && (
                <div className="flex gap-1 flex-shrink-0">
                  <button onClick={() => { setEditingId(a.id); setEditValue(a.answer || ""); }}
                    title="Edit" className="p-1.5 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800"><Pencil size={14} /></button>
                  <button onClick={async () => {
                    if (!confirm("Delete this saved answer?")) return;
                    try { await api.answers.remove(a.id); toast.success("Deleted"); load(); }
                    catch (e: any) { toast.error(e.message); }
                  }} title="Delete" className="p-1.5 rounded text-zinc-500 hover:text-red-400 hover:bg-zinc-800"><Trash2 size={14} /></button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PendingInbox({ pending, onResolved }: { pending: PendingQuestion[]; onResolved: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({});

  return (
    <div className="card p-5 border-amber-800/50 bg-amber-950/10">
      <div className="flex items-center gap-2 mb-3">
        <HelpCircle size={18} className="text-amber-400" />
        <h2 className="font-semibold text-amber-300">
          {pending.length} question{pending.length !== 1 ? "s" : ""} waiting on your answer
        </h2>
      </div>
      <p className="text-xs text-zinc-400 mb-4">
        These applications are paused until you answer. Your answer is saved and reused automatically — and the paused application resumes on its own.
      </p>
      <div className="space-y-3">
        {pending.map(p => (
          <div key={p.pending_id} className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
            <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1.5">
              <Building2 size={12} />
              <span>{p.job_title || "Application"}{p.job_company ? ` · ${p.job_company}` : ""}</span>
            </div>
            <p className="text-sm font-medium text-zinc-200 mb-2">{p.question_text}</p>
            <div className="flex items-center gap-2">
              {p.options && p.options.length > 0 ? (
                <select value={values[p.pending_id] || ""} onChange={e => setValues(v => ({ ...v, [p.pending_id]: e.target.value }))} className="input flex-1">
                  <option value="">Select…</option>
                  {p.options.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input value={values[p.pending_id] || ""} onChange={e => setValues(v => ({ ...v, [p.pending_id]: e.target.value }))}
                  placeholder="Your answer…" className="input flex-1"
                  type={p.question_type === "numeric" ? "number" : "text"} />
              )}
              <button onClick={async () => {
                const val = (values[p.pending_id] || "").trim();
                if (!val) { toast.error("Enter an answer first"); return; }
                try {
                  const r = await api.answers.answerPending(p.pending_id, val);
                  toast.success(r.requeued_applications > 0 ? `Saved — ${r.requeued_applications} application resumed` : "Saved");
                  onResolved();
                } catch (e: any) { toast.error(e.message); }
              }} className="btn-primary text-xs py-2">Save</button>
              <button onClick={async () => {
                try { await api.answers.skipPending(p.pending_id); onResolved(); }
                catch (e: any) { toast.error(e.message); }
              }} className="btn-ghost text-xs py-2 text-zinc-500">Skip</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AddAnswerRow({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => void }) {
  const [question, setQuestion] = useState("");
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  return (
    <div className="card p-4 space-y-2 border-amber-800/40">
      <input value={question} onChange={e => setQuestion(e.target.value)} placeholder="Question (e.g. 'Do you have a valid work visa?')" className="input" autoFocus />
      <div className="flex items-center gap-2">
        <input value={value} onChange={e => setValue(e.target.value)} placeholder="Your answer" className="input flex-1" />
        <button disabled={saving} onClick={async () => {
          if (!question.trim() || !value.trim()) { toast.error("Both fields are required"); return; }
          setSaving(true);
          try { await api.answers.create({ question_text: question.trim(), value: value.trim() }); toast.success("Saved"); onSaved(); }
          catch (e: any) { toast.error(e.message); } finally { setSaving(false); }
        }} className="btn-primary text-xs py-2">Save</button>
        <button onClick={onCancel} className="btn-ghost text-xs py-2 text-zinc-500">Cancel</button>
      </div>
    </div>
  );
}
