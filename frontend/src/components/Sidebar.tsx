// Codebase list (FR-006, FR-007, task T058) with the U1 re-ingest badge (task T139).
import { isInProgress, type Codebase } from "../api/client";

const STATUS_STYLE: Record<string, string> = {
  ready: "text-emerald-700 dark:text-emerald-400",
  failed: "text-red-700 dark:text-red-400",
  queued: "text-slate-500",
  ingesting: "text-sky-700 dark:text-sky-400",
};

interface Props {
  codebases: Codebase[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onReingest: (id: string) => void;
}

const iconButton =
  "rounded px-1.5 py-0.5 text-xs hover:bg-slate-200 disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:hover:bg-slate-800";

export function CodebaseList({ codebases, selectedId, onSelect, onDelete, onReingest }: Props) {
  if (codebases.length === 0) return <p className="px-2 text-sm text-slate-500">No codebases yet.</p>;
  return (
    <ul className="space-y-1">
      {codebases.map((c) => (
        <li key={c.id} className={`rounded p-2 ${c.id === selectedId ? "bg-slate-100 dark:bg-slate-800" : ""}`}>
          <button
            type="button"
            onClick={() => onSelect(c.id)}
            aria-current={c.id === selectedId || undefined}
            className="w-full truncate text-left text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
          >
            {c.name}
          </button>
          <div className="mt-1 flex items-center gap-2 text-xs">
            <span className={STATUS_STYLE[c.status]}>{c.status}</span>
            {c.reingest_required && (
              <span className="rounded bg-amber-100 px-1.5 text-amber-900 dark:bg-amber-900 dark:text-amber-100">
                Re-ingest required
              </span>
            )}
            <span className="ml-auto flex gap-1">
              <button
                type="button"
                aria-label={`Re-ingest ${c.name}`}
                title="Re-ingest"
                disabled={isInProgress(c.status)}
                onClick={() => onReingest(c.id)}
                className={iconButton}
              >
                ↻
              </button>
              <button
                type="button"
                aria-label={`Delete ${c.name}`}
                title="Delete"
                disabled={isInProgress(c.status)}
                onClick={() => {
                  if (window.confirm(`Delete ${c.name} and its conversations?`)) onDelete(c.id);
                }}
                className={iconButton}
              >
                ✕
              </button>
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
