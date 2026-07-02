"use client";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { AlertTriangle, XCircle, X, Settings } from "lucide-react";
import Link from "next/link";
import type { PlatformSession } from "@/types";

export function SessionBanner() {
  const [sessions, setSessions] = useState<PlatformSession[]>([]);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    api.sessions.list()
      .then((data) => setSessions(data.sessions || []))
      .catch(() => {});
  }, []);

  if (dismissed) return null;

  const expired = sessions.filter(
    (s) => s.status === "expired" || s.status === "invalid"
  );
  const connected = sessions.filter((s) => s.status === "active");
  const allExpired = expired.length > 0 && connected.length === 0;

  if (expired.length === 0) return null;

  if (allExpired) {
    return (
      <div className="relative flex items-center gap-3 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 mb-4">
        <XCircle size={18} className="text-red-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-red-300">
            Auto-apply paused — all job board sessions expired
          </p>
          <p className="text-xs text-red-400/70 mt-0.5">
            Reconnect your accounts to resume automatic job applications.
          </p>
        </div>
        <Link
          href="/settings"
          className="text-xs px-3 py-1.5 rounded-lg bg-red-500/20 border border-red-500/40 text-red-300 hover:bg-red-500/30 transition-colors flex-shrink-0"
        >
          <Settings size={12} className="inline mr-1" />
          Reconnect
        </Link>
        <button
          onClick={() => setDismissed(true)}
          className="p-1 rounded text-red-500/50 hover:text-red-400 transition-colors"
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  const names = expired.map((s) => s.display_name).join(", ");
  return (
    <div className="relative flex items-center gap-3 px-4 py-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30 mb-4">
      <AlertTriangle size={18} className="text-yellow-400 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-yellow-300">
          {names} session{expired.length > 1 ? "s" : ""} expired
        </p>
        <p className="text-xs text-yellow-400/70 mt-0.5">
          Auto-apply is paused for {names} jobs. Other platforms are unaffected.
        </p>
      </div>
      <Link
        href="/settings"
        className="text-xs px-3 py-1.5 rounded-lg bg-yellow-500/20 border border-yellow-500/40 text-yellow-300 hover:bg-yellow-500/30 transition-colors flex-shrink-0"
      >
        Reconnect
      </Link>
      <button
        onClick={() => setDismissed(true)}
        className="p-1 rounded text-yellow-500/50 hover:text-yellow-400 transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  );
}
