"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import {
  Wifi, WifiOff, RefreshCw, Unplug, ExternalLink, Loader2,
  CheckCircle, AlertTriangle, XCircle, Clock,
} from "lucide-react";
import toast from "react-hot-toast";

type SessionStatus = {
  platform: string;
  display_name: string;
  status: string;
  masked_username?: string;
  captured_at?: string;
  expires_at?: string;
  last_used_at?: string;
  last_validated_at?: string;
  use_count?: number;
  success_rate?: number;
  health?: string;
};

const HEALTH_STYLES = {
  green: { bg: "bg-green-500/10", border: "border-green-500/30", text: "text-green-400", icon: CheckCircle },
  yellow: { bg: "bg-yellow-500/10", border: "border-yellow-500/30", text: "text-yellow-400", icon: AlertTriangle },
  red: { bg: "bg-red-500/10", border: "border-red-500/30", text: "text-red-400", icon: XCircle },
};

function timeAgo(dateStr?: string): string {
  if (!dateStr) return "never";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function daysUntil(dateStr?: string): string {
  if (!dateStr) return "unknown";
  const diff = new Date(dateStr).getTime() - Date.now();
  const days = Math.ceil(diff / 86400000);
  if (days < 0) return "expired";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

export function SessionConnections() {
  const [sessions, setSessions] = useState<SessionStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [pollingToken, setPollingToken] = useState<string | null>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      const data = await api.sessions.list();
      setSessions(data.sessions || []);
    } catch {
      // Sessions endpoint may not be available yet
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSessions();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [loadSessions]);

  const startConnect = async (platform: string) => {
    setConnecting(platform);
    try {
      const data = await api.sessions.connect(platform);
      setPollingToken(data.handshake_token);
      toast.success(`Browser opening for ${platform} login...`);

      pollRef.current = setInterval(async () => {
        try {
          const status = await api.sessions.pollHandshake(data.handshake_token);
          if (status.status === "completed") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setConnecting(null);
            setPollingToken(null);
            toast.success(`${platform} connected securely!`);
            loadSessions();
          } else if (status.status === "failed" || status.status === "timeout") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setConnecting(null);
            setPollingToken(null);
            toast.error(status.error_message || `${platform} login ${status.status}`);
          }
        } catch {
          // Polling error — keep trying
        }
      }, 3000);

      // Timeout after 11 minutes
      setTimeout(() => {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setConnecting(null);
          setPollingToken(null);
        }
      }, 11 * 60 * 1000);
    } catch (e: any) {
      setConnecting(null);
      toast.error(e.message || "Could not start connection");
    }
  };

  const reconnect = async (platform: string) => {
    setConnecting(platform);
    try {
      const data = await api.sessions.reconnect(platform);
      setPollingToken(data.handshake_token);
      toast.success(`Browser opening for ${platform} re-login...`);

      pollRef.current = setInterval(async () => {
        try {
          const status = await api.sessions.pollHandshake(data.handshake_token);
          if (status.status === "completed") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setConnecting(null);
            setPollingToken(null);
            toast.success(`${platform} reconnected!`);
            loadSessions();
          } else if (status.status === "failed" || status.status === "timeout") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setConnecting(null);
            setPollingToken(null);
            toast.error(status.error_message || `Re-login ${status.status}`);
          }
        } catch {}
      }, 3000);
    } catch (e: any) {
      setConnecting(null);
      toast.error(e.message || "Could not reconnect");
    }
  };

  const disconnect = async (platform: string) => {
    try {
      await api.sessions.disconnect(platform);
      toast.success(`${platform} disconnected`);
      loadSessions();
    } catch (e: any) {
      toast.error(e.message || "Could not disconnect");
    }
  };

  const refreshSession = async (platform: string) => {
    try {
      const result = await api.sessions.refresh(platform);
      if (result.valid) {
        toast.success(`${platform} session is valid`);
      } else {
        toast.error(`${platform} session is no longer valid`);
      }
      loadSessions();
    } catch (e: any) {
      toast.error(e.message || "Could not refresh");
    }
  };

  if (loading) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-2 mb-2">
          <Wifi size={16} className="text-amber-400" />
          <h2 className="font-semibold">Job Board Connections</h2>
        </div>
        <div className="flex items-center gap-2 text-sm text-zinc-500">
          <Loader2 size={14} className="animate-spin" /> Loading sessions...
        </div>
      </div>
    );
  }

  return (
    <div className="card p-6 space-y-4">
      <div className="flex items-center gap-2 mb-1">
        <Wifi size={16} className="text-amber-400" />
        <h2 className="font-semibold">Job Board Connections</h2>
      </div>
      <p className="text-xs text-zinc-500">
        Connect your job board accounts securely. You log in through your browser — we capture the session cookies and encrypt them. No passwords are stored.
      </p>

      <div className="space-y-3">
        {sessions.map((session) => {
          const health = HEALTH_STYLES[session.health as keyof typeof HEALTH_STYLES] || HEALTH_STYLES.red;
          const HealthIcon = health.icon;
          const isConnecting = connecting === session.platform;

          return (
            <div
              key={session.platform}
              className={`flex items-center justify-between px-4 py-3 rounded-lg border ${health.bg} ${health.border}`}
            >
              <div className="flex items-center gap-3 min-w-0">
                <HealthIcon size={16} className={health.text} />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium">{session.display_name}</p>
                    {session.status === "active" && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/20 text-green-400">Connected</span>
                    )}
                    {session.status === "expired" && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400">Expired</span>
                    )}
                    {session.status === "invalid" && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400">Invalid</span>
                    )}
                  </div>
                  {session.status !== "not_connected" && (
                    <div className="flex items-center gap-3 text-[11px] text-zinc-500 mt-0.5">
                      {session.masked_username && <span>{session.masked_username}</span>}
                      {session.last_used_at && <span>Used {timeAgo(session.last_used_at)}</span>}
                      {session.use_count != null && session.use_count > 0 && (
                        <span>{session.use_count} apps</span>
                      )}
                      {session.success_rate != null && session.use_count != null && session.use_count > 0 && (
                        <span>{Math.round(session.success_rate * 100)}% success</span>
                      )}
                      {session.expires_at && session.status === "active" && (
                        <span className="flex items-center gap-0.5">
                          <Clock size={10} /> Expires {daysUntil(session.expires_at)}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-1.5 flex-shrink-0 ml-3">
                {isConnecting ? (
                  <div className="flex items-center gap-2 text-xs text-amber-400">
                    <Loader2 size={14} className="animate-spin" />
                    <span>Waiting for login...</span>
                  </div>
                ) : session.status === "not_connected" ? (
                  <button
                    onClick={() => startConnect(session.platform)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/40 text-amber-300 hover:bg-amber-500/20 transition-colors flex items-center gap-1.5"
                  >
                    <ExternalLink size={12} /> Connect
                  </button>
                ) : (
                  <>
                    {session.status === "active" && (
                      <button
                        onClick={() => refreshSession(session.platform)}
                        className="p-1.5 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-700/50 transition-colors"
                        title="Validate session"
                      >
                        <RefreshCw size={13} />
                      </button>
                    )}
                    {(session.status === "expired" || session.status === "invalid") && (
                      <button
                        onClick={() => reconnect(session.platform)}
                        className="text-xs px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/40 text-amber-300 hover:bg-amber-500/20 transition-colors"
                      >
                        Reconnect
                      </button>
                    )}
                    <button
                      onClick={() => disconnect(session.platform)}
                      className="p-1.5 rounded text-zinc-600 hover:text-red-400 hover:bg-zinc-700/50 transition-colors"
                      title="Disconnect"
                    >
                      <Unplug size={13} />
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-xs text-zinc-600">
        Sessions expire automatically based on each platform's policy. You'll be notified when re-authentication is needed.
      </p>
    </div>
  );
}
