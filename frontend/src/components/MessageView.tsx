// One chat message (FR-010/011, C4, FR-040/041; tasks T144, T146). Markdown without raw HTML.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { CitationRef, Message } from "../api/client";
import { citationsToLinks, parseCiteHref } from "./citations";

interface Props {
  message: Message;
  streaming?: boolean;
  onCite: (citation: CitationRef) => void;
  onFeedback: (messageId: string, value: 1 | -1 | null) => void;
}

const STATUS_NOTE: Partial<Record<Message["status"], string>> = {
  unverified: "Unverified: no valid citation backs this answer.",
  declined: "Outside what CodeCompass answers.",
  error: "The answer was interrupted.",
};

export function MessageView({ message, streaming = false, onCite, onFeedback }: Props) {
  if (message.role === "user") {
    return (
      <div className="ml-auto max-w-[80%] rounded-lg bg-sky-50 px-3 py-2 text-sm dark:bg-sky-950">{message.content}</div>
    );
  }
  const note = STATUS_NOTE[message.status];
  const feedbackButton = (value: 1 | -1, label: string, icon: string) => (
    <button
      type="button"
      aria-label={label}
      aria-pressed={message.feedback === value}
      onClick={() => onFeedback(message.id, message.feedback === value ? null : value)}
      className={`rounded px-1.5 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:hover:bg-slate-800 ${
        message.feedback === value ? "bg-slate-200 dark:bg-slate-700" : ""
      }`}
    >
      {icon}
    </button>
  );

  return (
    <div className="max-w-[90%] space-y-2 text-sm">
      {note && (
        <p className="inline-block rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900 dark:bg-amber-900 dark:text-amber-100">
          {note}
        </p>
      )}
      <div className="prose prose-sm max-w-none dark:prose-invert">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          skipHtml
          components={{
            a: ({ href, children }) => {
              const cite = parseCiteHref(href);
              if (cite) {
                return (
                  <button
                    type="button"
                    onClick={() => onCite(cite)}
                    className="mx-0.5 rounded bg-slate-100 px-1 font-mono text-xs text-sky-700 hover:bg-sky-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:bg-slate-800 dark:text-sky-300"
                  >
                    {children}
                  </button>
                );
              }
              return (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              );
            },
          }}
        >
          {citationsToLinks(message.content)}
        </ReactMarkdown>
        {streaming && <span className="animate-pulse">▍</span>}
      </div>
      {!streaming && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          {feedbackButton(1, "Helpful", "👍")}
          {feedbackButton(-1, "Not helpful", "👎")}
          {message.trace_url && (
            <a href={message.trace_url} target="_blank" rel="noreferrer" className="underline hover:text-sky-600">
              Open in Langfuse
            </a>
          )}
        </div>
      )}
    </div>
  );
}
