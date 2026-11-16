// Ingestion progress and final summary (FR-004, task T057).
import { useState } from "react";
import type { Codebase } from "../api/client";

const STAGE_LABEL: Record<string, string> = {
  downloading: "Downloading",
  filtering: "Selecting files",
  chunking: "Splitting code into chunks",
  embedding: "Embedding chunks",
  overview: "Building overview",
  finalizing: "Finalizing",
};

function percent(codebase: Codebase): number {
  const p = codebase.progress;
  if (!p) return 0;
  if (p.chunks_total > 0) return Math.round((p.chunks_done / p.chunks_total) * 100);
  if (p.files_total > 0) return Math.round((p.files_done / p.files_total) * 50);
  return 0;
}

export function IngestProgress({ codebase, onRetry }: { codebase: Codebase; onRetry: () => void }) {
  const [showSkipped, setShowSkipped] = useState(false);
  const { status, progress, summary } = codebase;

  return (
    <section aria-label="Ingestion" className="max-w-2xl space-y-4">
      <h2 className="text-lg font-semibold">{codebase.name}</h2>

      {status === "queued" && <p className="text-sm text-slate-500">Waiting for another ingestion to finish…</p>}

      {status === "ingesting" && progress && (
        <div className="space-y-2">
          <p className="text-sm">{STAGE_LABEL[progress.stage] ?? progress.stage}…</p>
          <div
            role="progressbar"
            aria-label="Ingestion progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent(codebase)}
            className="h-2 w-full overflow-hidden rounded bg-slate-200 dark:bg-slate-800"
          >
            <div className="h-full bg-sky-600 transition-all" style={{ width: `${percent(codebase)}%` }} />
          </div>
          <p className="text-xs text-slate-500">
            {progress.files_done} / {progress.files_total} files · {progress.chunks_done} / {progress.chunks_total} chunks
          </p>
        </div>
      )}

      {codebase.error && (
        <div role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
          <p>{codebase.error}</p>
          {status === "failed" && (
            <button type="button" onClick={onRetry} className="mt-2 rounded border border-red-400 px-3 py-1 text-xs font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500">
              Retry
            </button>
          )}
        </div>
      )}

      {summary && (
        <div className="space-y-2">
          <p className="text-sm">
            <strong>{summary.indexed} files indexed</strong> ({(summary.bytes_indexed / 1_000_000).toFixed(1)} MB)
            {codebase.commit_sha && <span className="text-slate-500"> at {codebase.commit_sha.slice(0, 7)}</span>}
          </p>
          {Object.keys(summary.skipped_by_reason).length > 0 && (
            <table className="text-sm">
              <caption className="text-left text-xs text-slate-500">Skipped, by reason</caption>
              <tbody>
                {Object.entries(summary.skipped_by_reason)
                  .sort(([, a], [, b]) => b - a)
                  .map(([reason, count]) => (
                    <tr key={reason}>
                      <td className="pr-4">{reason}</td>
                      <td>{count}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
          {summary.skipped.length > 0 && (
            <details onToggle={(e) => setShowSkipped((e.target as HTMLDetailsElement).open)}>
              <summary className="cursor-pointer text-xs text-slate-500">Show skipped files</summary>
              {showSkipped && (
                <ul className="mt-1 max-h-60 overflow-y-auto text-xs">
                  {summary.skipped.map((s) => (
                    <li key={s.path}>
                      <span>{s.path}</span> <span className="text-slate-500">({s.reason})</span>
                    </li>
                  ))}
                </ul>
              )}
            </details>
          )}
        </div>
      )}
    </section>
  );
}
