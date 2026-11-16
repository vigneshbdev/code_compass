// Application shell (task T028): sidebar | main | drawer. US1 adds codebases (T056-T058).
import { useState } from "react";
import { CodebaseList } from "./components/Sidebar";
import { HealthBanner, isBlocking } from "./components/HealthBanner";
import { IngestForm } from "./components/IngestForm";
import { Chat } from "./components/Chat";
import { CodeViewer } from "./components/CodeViewer";
import { IngestProgress } from "./components/IngestProgress";
import { OverviewPanel } from "./components/OverviewPanel";
import type { CitationRef } from "./api/client";
import { useCodebase, useCodebases, useDeleteCodebase, useHealth, useOverview, useReingest } from "./api/queries";
import { useTheme } from "./hooks/useTheme";

export function App() {
  const { theme, toggle } = useTheme();
  const health = useHealth();
  const codebases = useCodebases();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [citation, setCitation] = useState<CitationRef | null>(null);
  const selected = useCodebase(adding ? null : selectedId);
  const remove = useDeleteCodebase();
  const reingest = useReingest();
  const overview = useOverview(selectedId, Boolean(selected.data?.summary));
  const blocked = health.data ? isBlocking(health.data) : false;

  return (
    <div className="flex h-screen flex-col bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2 dark:border-slate-800">
        <h1 className="text-base font-semibold">CodeCompass</h1>
        <button
          type="button"
          onClick={toggle}
          className="rounded px-2 py-1 text-sm hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:hover:bg-slate-800"
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? "☀︎ Light" : "☾ Dark"}
        </button>
      </header>
      {health.data && <HealthBanner health={health.data} />}
      {health.isError && (
        <div role="alert" className="bg-red-50 px-4 py-2 text-sm text-red-900 dark:bg-red-950 dark:text-red-100">
          The CodeCompass server is not responding.
        </div>
      )}
      <div className="flex min-h-0 flex-1" aria-hidden={blocked || undefined}>
        <nav aria-label="Codebases and conversations" className="w-72 shrink-0 space-y-3 overflow-y-auto border-r border-slate-200 p-3 dark:border-slate-800">
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="w-full rounded border border-dashed border-slate-300 px-3 py-2 text-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:border-slate-700 dark:hover:bg-slate-900"
          >
            + Add codebase
          </button>
          <CodebaseList
            codebases={codebases.data ?? []}
            selectedId={adding ? null : selectedId}
            onSelect={(id) => {
              setSelectedId(id);
              setAdding(false);
              setCitation(null);
            }}
            onDelete={(id) => {
              remove.mutate(id);
              if (id === selectedId) setSelectedId(null);
            }}
            onReingest={(id) => reingest.mutate(id)}
          />
        </nav>
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto p-6">
          {adding || (!selectedId && (codebases.data?.length ?? 0) === 0) ? (
            <IngestForm
              onCreated={(c) => {
                setSelectedId(c.id);
                setAdding(false);
              }}
            />
          ) : selected.data ? (
            selected.data.summary && !selected.data.reingest_required ? (
              <div className="flex h-full min-h-0 flex-col gap-4">
                <details className="text-sm">
                  <summary className="cursor-pointer font-semibold">{selected.data.name}</summary>
                  <div className="mt-2 space-y-4">
                    {overview.data && <OverviewPanel overview={overview.data} />}
                    <IngestProgress codebase={selected.data} onRetry={() => reingest.mutate(selected.data.id)} />
                  </div>
                </details>
                <div className="min-h-0 flex-1">
                  <Chat
                    key={selected.data.id}
                    codebase={selected.data}
                    onCite={setCitation}
                    starters={overview.data?.starter_questions ?? []}
                  />
                </div>
              </div>
            ) : (
              <IngestProgress codebase={selected.data} onRetry={() => reingest.mutate(selected.data.id)} />
            )
          ) : (
            <p className="text-sm text-slate-500">Select a codebase.</p>
          )}
        </main>
        {citation && selectedId && !adding && (
          <CodeViewer codebaseId={selectedId} citation={citation} onClose={() => setCitation(null)} />
        )}
      </div>
    </div>
  );
}
