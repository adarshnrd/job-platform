"use client";
import { KanbanColumn, Application } from "@/types";
import { ApplicationCard } from "./application-card";
import { cn } from "@/lib/utils";

const COLUMN_COLORS: Record<string, string> = {
  matched:     "border-blue-500/30",
  applied:     "border-green-500/30",
  in_progress: "border-cyan-500/30",
  interviews:  "border-violet-500/30",
  offers:      "border-emerald-500/30",
  closed:      "border-zinc-600/30",
};

export function PipelineKanban({ columns, onUpdate }: { columns: KanbanColumn[]; onUpdate: () => void }) {
  if (!columns.length) {
    return (
      <div className="card p-12 text-center">
        <p className="text-zinc-500">No applications yet. Click "Discover Jobs" to find matches.</p>
      </div>
    );
  }

  return (
    <div className="flex gap-4 overflow-x-auto pb-4 min-h-[500px]">
      {columns.map(col => (
        <div key={col.id} className={cn("flex-shrink-0 w-72 card border-t-2 p-3 flex flex-col", COLUMN_COLORS[col.id])}>
          {/* Column header */}
          <div className="flex items-center justify-between mb-3 px-1">
            <span className="text-sm font-semibold">{col.title}</span>
            <span className="text-xs bg-zinc-800 text-zinc-400 rounded-full px-2 py-0.5 font-mono">{col.count}</span>
          </div>

          {/* Cards */}
          <div className="flex-1 space-y-2 overflow-y-auto max-h-[600px]">
            {col.applications.length === 0 ? (
              <div className="text-center py-8 text-zinc-600 text-xs">No applications</div>
            ) : (
              col.applications.map(app => (
                <ApplicationCard key={app.id} application={app} onUpdate={onUpdate} />
              ))
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
