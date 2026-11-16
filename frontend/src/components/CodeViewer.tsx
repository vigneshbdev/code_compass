// Code viewer drawer (FR-012, task T144): line numbers, cited range highlighted.
import { useEffect, useRef } from "react";
import { Highlight, themes } from "prism-react-renderer";
import { useQuery } from "@tanstack/react-query";
import { apiFetch, type CitationRef, type FileContent } from "../api/client";

const PRISM_LANGUAGE: Record<string, string> = {
  python: "python", javascript: "javascript", typescript: "typescript", tsx: "tsx",
  markdown: "markdown", yaml: "yaml", json: "json", toml: "toml", shell: "bash",
  dockerfile: "docker", sql: "sql", css: "css", html: "markup", go: "go", rust: "rust",
};

interface ViewProps {
  path: string;
  language: string;
  content: string;
  start: number;
  end: number;
  redactions: number;
}

export function CodeView({ path, language, content, start, end, redactions }: ViewProps) {
  const firstHighlighted = useRef<HTMLDivElement>(null);
  useEffect(() => {
    firstHighlighted.current?.scrollIntoView?.({ block: "center" });
  }, [path, start]);

  return (
    <div className="text-xs">
      <div className="mb-2 flex items-center gap-2">
        <code className="font-semibold">{path}</code>
        <span className="text-slate-500">lines {start}–{end}</span>
        {redactions > 0 && (
          <span className="rounded bg-amber-100 px-1.5 text-amber-900 dark:bg-amber-900 dark:text-amber-100">
            {redactions} secrets redacted
          </span>
        )}
      </div>
      <Highlight theme={themes.vsDark} code={content} language={PRISM_LANGUAGE[language] ?? "text"}>
        {({ tokens, getLineProps, getTokenProps }) => (
          <pre className="overflow-x-auto rounded bg-slate-900 p-2 font-mono leading-5">
            {tokens.map((line, i) => {
              const n = i + 1;
              const highlighted = n >= start && n <= end;
              const { key, ...lineProps } = getLineProps({ line });
              return (
                <div
                  key={n}
                  {...lineProps}
                  ref={n === start ? firstHighlighted : undefined}
                  data-testid="line"
                  data-line={n}
                  data-highlighted={highlighted}
                  className={`${lineProps.className ?? ""} ${highlighted ? "bg-sky-900/70" : ""}`}
                >
                  <span className="mr-3 inline-block w-8 select-none text-right text-slate-500">{n}</span>
                  {line.map((token, j) => {
                    const { key, ...tokenProps } = getTokenProps({ token });
                    return <span key={j} {...tokenProps} />;
                  })}
                </div>
              );
            })}
          </pre>
        )}
      </Highlight>
    </div>
  );
}

export function CodeViewer({
  codebaseId,
  citation,
  onClose,
}: {
  codebaseId: string;
  citation: CitationRef;
  onClose: () => void;
}) {
  const file = useQuery({
    queryKey: ["file", codebaseId, citation.path],
    queryFn: () =>
      apiFetch<FileContent>(`/codebases/${codebaseId}/files?path=${encodeURIComponent(citation.path)}`),
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      aria-label="Code viewer"
      className="flex w-[44rem] max-w-[55vw] shrink-0 flex-col border-l border-slate-200 dark:border-slate-800"
    >
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 dark:border-slate-800">
        <span className="text-sm font-medium">Source</span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close code viewer"
          className="rounded px-2 text-sm hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:hover:bg-slate-800"
        >
          ✕
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {file.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
        {file.error && <p role="alert" className="text-sm text-red-600">{(file.error as Error).message}</p>}
        {file.data && (
          <CodeView
            path={file.data.path}
            language={file.data.language}
            content={file.data.content}
            start={citation.start_line}
            end={citation.end_line}
            redactions={file.data.redaction_count}
          />
        )}
      </div>
    </aside>
  );
}
