// FR-004: ingestion progress and the indexed/skipped summary (task T057).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Codebase } from "../api/client";
import { IngestProgress } from "./IngestProgress";

const base: Codebase = {
  id: "c1",
  name: "fastapi/full-stack-fastapi-template",
  source_type: "github",
  source_url: "https://github.com/fastapi/full-stack-fastapi-template",
  source_ref: null,
  commit_sha: "abc1234def",
  status: "ingesting",
  error: null,
  error_code: null,
  reingest_required: false,
  progress: { stage: "embedding", files_done: 120, files_total: 120, chunks_done: 400, chunks_total: 800 },
  summary: null,
  created_at: "2026-11-16T10:00:00Z",
  updated_at: "2026-11-16T10:00:00Z",
};

describe("IngestProgress", () => {
  it("shows the stage and an accessible progress bar while ingesting", () => {
    render(<IngestProgress codebase={base} onRetry={() => {}} />);
    expect(screen.getByText(/embedding/i)).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByText(/400 \/ 800 chunks/)).toBeInTheDocument();
  });

  it("shows the waiting state when queued", () => {
    render(<IngestProgress codebase={{ ...base, status: "queued", progress: null }} onRetry={() => {}} />);
    expect(screen.getByText(/waiting for another ingestion/i)).toBeInTheDocument();
  });

  it("summarises indexed and skipped files by reason, with an expandable list", async () => {
    const ready: Codebase = {
      ...base,
      status: "ready",
      summary: {
        indexed: 310,
        skipped: [
          { path: "frontend/package-lock.json", reason: "lockfile" },
          { path: "logo.png", reason: "binary" },
        ],
        skipped_by_reason: { lockfile: 2, binary: 14 },
        bytes_indexed: 1_830_000,
      },
    };
    render(<IngestProgress codebase={ready} onRetry={() => {}} />);
    expect(screen.getByText(/310 files indexed/i)).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /lockfile 2/i })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /binary 14/i })).toBeInTheDocument();
    expect(screen.queryByText("logo.png")).toBeNull();
    await userEvent.click(screen.getByText(/show skipped files/i));
    expect(screen.getByText("logo.png")).toBeInTheDocument();
  });

  it("shows the error with a retry action when failed", async () => {
    const onRetry = vi.fn();
    const failed: Codebase = {
      ...base,
      status: "failed",
      progress: null,
      error: "The codebase has 9000 indexable files; the limit is 5000 files.",
      error_code: "repo_too_large",
    };
    render(<IngestProgress codebase={failed} onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/limit is 5000 files/);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
