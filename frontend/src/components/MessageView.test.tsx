// C4 unverified badge, FR-041 feedback, FR-040 Langfuse link, FR-011 citation chips (T144, T146).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Message } from "../api/client";
import { MessageView } from "./MessageView";

const base: Message = {
  id: "m1",
  seq: 2,
  role: "assistant",
  status: "complete",
  content: "Parsing lives in [app/core/config.py:8-17].",
  citations: [{ path: "app/core/config.py", start_line: 8, end_line: 17 }],
  trace_id: "t1",
  trace_url: "http://localhost:3000/project/p/traces/t1",
  feedback: null,
  usage: null,
  created_at: "2026-11-16T10:00:00Z",
};

describe("MessageView", () => {
  it("renders citations as buttons that open the code", async () => {
    const onCite = vi.fn();
    render(<MessageView message={base} onCite={onCite} onFeedback={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /app\/core\/config.py:8-17/ }));
    expect(onCite).toHaveBeenCalledWith({ path: "app/core/config.py", start_line: 8, end_line: 17 });
  });

  it("links to the Langfuse trace and records feedback", async () => {
    const onFeedback = vi.fn();
    render(<MessageView message={base} onCite={() => {}} onFeedback={onFeedback} />);
    expect(screen.getByRole("link", { name: /open in langfuse/i })).toHaveAttribute("href", base.trace_url);
    await userEvent.click(screen.getByRole("button", { name: "Helpful" }));
    expect(onFeedback).toHaveBeenCalledWith("m1", 1);
  });

  it("marks answers without a valid citation as unverified (C4)", () => {
    render(<MessageView message={{ ...base, status: "unverified", citations: [] }} onCite={() => {}} onFeedback={() => {}} />);
    expect(screen.getByText(/unverified/i)).toBeInTheDocument();
  });

  it("never renders raw HTML from the model", () => {
    const { container } = render(
      <MessageView message={{ ...base, content: "<img src=x onerror=alert(1)> hi" }} onCite={() => {}} onFeedback={() => {}} />,
    );
    expect(container.querySelector("img")).toBeNull();
  });
});
