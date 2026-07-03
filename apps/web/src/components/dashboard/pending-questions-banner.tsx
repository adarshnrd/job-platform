"use client";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { HelpCircle, X } from "lucide-react";
import Link from "next/link";

export function PendingQuestionsBanner() {
  const [count, setCount] = useState(0);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    api.answers.pending()
      .then((data) => setCount((data.pending || []).length))
      .catch(() => {});
  }, []);

  if (dismissed || count === 0) return null;

  return (
    <div className="relative flex items-center gap-3 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/30 mb-4">
      <HelpCircle size={18} className="text-amber-400 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-amber-300">
          {count} application{count > 1 ? "s are" : " is"} waiting on your answer{count > 1 ? "s" : ""}
        </p>
        <p className="text-xs text-amber-400/70 mt-0.5">
          Answer once and paused applications resume automatically — your answers are reused everywhere.
        </p>
      </div>
      <Link
        href="/answers"
        className="text-xs px-3 py-1.5 rounded-lg bg-amber-500/20 border border-amber-500/40 text-amber-300 hover:bg-amber-500/30 transition-colors flex-shrink-0"
      >
        Answer now
      </Link>
      <button
        onClick={() => setDismissed(true)}
        className="p-1 rounded text-amber-500/50 hover:text-amber-400 transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  );
}
