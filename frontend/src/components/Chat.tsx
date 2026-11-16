// Chat screen (FR-010…FR-016, task T144): conversations, streaming answers, citations.
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { CitationRef, Codebase } from "../api/client";
import { useConversation, useConversations, useCreateConversation, useFeedback } from "../api/queries";
import { useChatStream } from "../hooks/useChatStream";
import { MessageView } from "./MessageView";

interface Props {
  codebase: Codebase;
  onCite: (citation: CitationRef) => void;
  starters?: string[];
}

/** Render with `key={codebase.id}` so state resets when the codebase changes. */
export function Chat({ codebase, onCite, starters = [] }: Props) {
  const conversations = useConversations(codebase.id);
  const [chosenId, setConversationId] = useState<string | null>(null);
  // Default to the most recent conversation without copying it into state.
  const conversationId = chosenId ?? conversations.data?.[0]?.id ?? null;
  const conversation = useConversation(conversationId);
  const create = useCreateConversation(codebase.id);
  const feedback = useFeedback(conversationId);
  const { pending, send, clearError } = useChatStream(conversationId, codebase.id);
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const ready = codebase.status === "ready" || (codebase.status === "ingesting" && codebase.summary !== null);
  const chatBlocked = !ready || codebase.reingest_required;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [conversation.data, pending?.message.content]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key === "/" && target.tagName !== "TEXTAREA" && target.tagName !== "INPUT") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || pending || chatBlocked) return;
    let id = conversationId;
    if (!id) {
      id = (await create.mutateAsync()).id;
      setConversationId(id);
    }
    setInput("");
    await send(text, id); // pass the id explicitly: a just-created conversation isn't in state yet
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void ask(input);
  }

  const messages = conversation.data?.messages ?? [];
  const progress = codebase.progress;

  return (
    <section aria-label="Chat" className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex items-center gap-2">
        <label className="text-xs text-slate-500" htmlFor="conversation-select">
          Conversation
        </label>
        <select
          id="conversation-select"
          value={conversationId ?? ""}
          onChange={(e) => setConversationId(e.target.value || null)}
          className="max-w-xs truncate rounded border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900"
        >
          {(conversations.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
          {!conversations.data?.length && <option value="">No conversations yet</option>}
        </select>
        <button
          type="button"
          onClick={() => void create.mutateAsync().then((c) => setConversationId(c.id))}
          className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:border-slate-700 dark:hover:bg-slate-900"
        >
          New conversation
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-2" aria-live="polite">
        {messages.length === 0 && !pending && (
          <div className="space-y-2">
            <p className="text-sm text-slate-500">Ask where something is implemented or how part of the code works.</p>
            {starters.length > 0 && (
              <ul aria-label="Starter questions" className="flex flex-wrap gap-2">
                {starters.map((q) => (
                  <li key={q}>
                    <button
                      type="button"
                      disabled={chatBlocked}
                      onClick={() => void ask(q)}
                      className="rounded-full border border-slate-300 px-3 py-1 text-left text-xs hover:bg-slate-50 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:border-slate-700 dark:hover:bg-slate-900"
                    >
                      {q}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {messages.map((m) => (
          <MessageView key={m.id} message={m} onCite={onCite} onFeedback={(id, value) => feedback.mutate({ messageId: id, value })} />
        ))}
        {pending && (
          <>
            <MessageView message={{ ...pending.message, id: "q", role: "user", content: pending.question }} onCite={onCite} onFeedback={() => {}} />
            <MessageView message={pending.message} streaming={!pending.error} onCite={onCite} onFeedback={() => {}} />
            {pending.error && (
              <p role="alert" className="text-sm text-red-700 dark:text-red-300">
                {pending.error}{" "}
                <button type="button" className="underline" onClick={clearError}>
                  Dismiss
                </button>
              </p>
            )}
          </>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="mt-3 flex gap-2">
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask(input);
            }
          }}
          disabled={chatBlocked}
          rows={2}
          aria-label="Ask a question about this codebase"
          placeholder={
            codebase.reingest_required
              ? "Re-ingest required: the embedding model changed."
              : chatBlocked
                ? `Indexing… ${progress?.chunks_total ? Math.round((progress.chunks_done / progress.chunks_total) * 100) : 0}%`
                : "Ask about the code (press / to focus, Enter to send)"
          }
          className="min-h-[2.5rem] flex-1 resize-none rounded border border-slate-300 bg-white px-3 py-2 text-sm disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900"
        />
        <button
          type="submit"
          disabled={chatBlocked || !!pending || !input.trim()}
          className="rounded bg-sky-600 px-4 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
        >
          Ask
        </button>
      </form>
    </section>
  );
}
