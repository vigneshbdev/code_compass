// Add a codebase from a public GitHub URL or a .zip (FR-001, FR-002, task T056).
import { useState, type FormEvent } from "react";
import { ApiError, type Codebase } from "../api/client";
import { useCreateFromGithub, useCreateFromZip } from "../api/queries";

const GITHUB_URL = /^https:\/\/github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9._-]+(\/tree\/\S+)?\/?$/;
type Mode = "github" | "zip";

export function IngestForm({ onCreated }: { onCreated: (codebase: Codebase) => void }) {
  const [mode, setMode] = useState<Mode>("github");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const github = useCreateFromGithub();
  const zip = useCreateFromZip();
  const pending = github.isPending || zip.isPending;
  const error = (mode === "github" ? github.error : zip.error) as ApiError | Error | null;
  const urlInvalid = url.trim() !== "" && !GITHUB_URL.test(url.trim());

  async function submit(event: FormEvent) {
    event.preventDefault();
    const created =
      mode === "github" ? await github.mutateAsync(url.trim()) : file ? await zip.mutateAsync(file) : undefined;
    if (created) onCreated(created);
  }

  const tab = (value: Mode, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === value}
      onClick={() => setMode(value)}
      className={`rounded px-3 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
        mode === value ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "hover:bg-slate-100 dark:hover:bg-slate-800"
      }`}
    >
      {label}
    </button>
  );

  return (
    <form onSubmit={(e) => void submit(e).catch(() => {})} className="max-w-xl space-y-4" aria-label="Add a codebase">
      <h2 className="text-lg font-semibold">Add a codebase</h2>
      <div role="tablist" className="flex gap-2">
        {tab("github", "GitHub URL")}
        {tab("zip", "Upload .zip")}
      </div>
      {mode === "github" ? (
        <label className="block text-sm">
          Public repository URL
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            aria-invalid={urlInvalid || undefined}
            aria-describedby="url-help"
            className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900"
          />
          <span id="url-help" className={`mt-1 block text-xs ${urlInvalid ? "text-red-600" : "text-slate-500"}`}>
            {urlInvalid ? "Use https://github.com/owner/repo (optionally /tree/branch)." : "Public repositories only."}
          </span>
        </label>
      ) : (
        <label className="block text-sm">
          Project archive (.zip)
          <input
            type="file"
            accept=".zip,application/zip"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
          <span className="mt-1 block text-xs text-slate-500">Local folder? Zip it first.</span>
        </label>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {error.message}
        </p>
      )}
      <button
        type="submit"
        disabled={pending || (mode === "github" ? !url.trim() || urlInvalid : !file)}
        className="rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      >
        {pending ? "Starting…" : "Index codebase"}
      </button>
    </form>
  );
}
