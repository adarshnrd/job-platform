"use client";
import { useEffect, useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { api } from "@/lib/api";
import { Resume } from "@/types";
import { Upload, FileText, Star, Trash2, CheckCircle } from "lucide-react";
import toast from "react-hot-toast";
import { formatDate, cn } from "@/lib/utils";

export function ResumeClient() {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [uploading, setUploading] = useState(false);
  const [name, setName] = useState("");

  const load = async () => {
    try {
      const data = await api.resumes.list();
      setResumes(data);
    } catch (e: any) { toast.error(e.message); }
  };

  useEffect(() => { load(); }, []);

  const onDrop = useCallback(async (files: File[]) => {
    const file = files[0];
    if (!file) return;
    const resumeName = name || file.name.replace(/\.[^.]+$/, "");
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("name", resumeName);
      formData.append("is_primary", resumes.length === 0 ? "true" : "false");
      await api.resumes.upload(formData);
      toast.success("Resume uploaded and parsed!");
      setName("");
      load();
    } catch (e: any) { toast.error(e.message || "Upload failed"); }
    finally { setUploading(false); }
  }, [name, resumes.length]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop, accept: { "application/pdf": [".pdf"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"] },
    maxFiles: 1, maxSize: 10 * 1024 * 1024,
  });

  const setPrimary = async (id: string) => {
    try { await api.resumes.setPrimary(id); toast.success("Primary resume updated"); load(); }
    catch (e: any) { toast.error(e.message); }
  };

  const deleteResume = async (id: string) => {
    if (!confirm("Delete this resume?")) return;
    try { await api.resumes.delete(id); toast.success("Deleted"); load(); }
    catch (e: any) { toast.error(e.message); }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold">Resume Manager</h1>
        <p className="text-sm text-zinc-400 mt-0.5">Upload multiple resumes. AI picks the best fit per job.</p>
      </div>

      {/* Upload */}
      <div className="card p-6 space-y-4">
        <h2 className="font-semibold">Upload Resume</h2>
        <input value={name} onChange={e => setName(e.target.value)} placeholder='Resume name (e.g. "React Frontend v2")' className="input" />
        <div {...getRootProps()} className={cn(
          "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors",
          isDragActive ? "border-amber-400 bg-amber-500/5" : "border-zinc-700 hover:border-zinc-500"
        )}>
          <input {...getInputProps()} />
          <Upload size={24} className="mx-auto mb-3 text-zinc-500" />
          {uploading ? (
            <p className="text-amber-400 font-medium">Uploading & parsing with AI...</p>
          ) : isDragActive ? (
            <p className="text-amber-400">Drop it here</p>
          ) : (
            <>
              <p className="text-zinc-300 font-medium">Drag & drop or click to upload</p>
              <p className="text-xs text-zinc-500 mt-1">PDF or DOCX · Max 10MB</p>
            </>
          )}
        </div>
      </div>

      {/* Resumes list */}
      {resumes.length > 0 && (
        <div className="space-y-3">
          <h2 className="font-semibold">Your Resumes</h2>
          {resumes.map(r => (
            <div key={r.id} className={cn("card p-4 flex items-center gap-4", r.is_primary ? "border-amber-500/30" : "")}>
              <FileText size={20} className={r.is_primary ? "text-amber-400" : "text-zinc-500"} />
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{r.name}</p>
                <p className="text-xs text-zinc-500">
                  {r.word_count ? `${r.word_count} words · ` : ""}
                  Uploaded {formatDate(r.created_at)}
                  {r.ats_score ? ` · ATS: ${r.ats_score}%` : ""}
                </p>
              </div>
              {r.is_primary && (
                <span className="flex items-center gap-1 text-xs text-amber-400 bg-amber-500/10 px-2 py-1 rounded-full">
                  <Star size={11} fill="currentColor" /> Primary
                </span>
              )}
              <div className="flex gap-2">
                {!r.is_primary && (
                  <button onClick={() => setPrimary(r.id)} className="btn-ghost text-xs flex items-center gap-1">
                    <CheckCircle size={12} /> Set Primary
                  </button>
                )}
                <a href={r.file_url} target="_blank" rel="noopener noreferrer" className="btn-ghost text-xs">View</a>
                <button onClick={() => deleteResume(r.id)} className="p-1.5 rounded hover:bg-red-900/30 text-zinc-500 hover:text-red-400 transition-colors">
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Skills extracted */}
      {resumes.some(r => r.parsed_data?.skills?.length) && (
        <div className="card p-4">
          <h2 className="font-semibold mb-3">Skills Extracted by AI</h2>
          <div className="flex flex-wrap gap-2">
            {resumes.find(r => r.is_primary)?.parsed_data?.skills?.map((skill: string) => (
              <span key={skill} className="text-xs bg-zinc-800 text-zinc-300 px-2.5 py-1 rounded-full border border-zinc-700">{skill}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
