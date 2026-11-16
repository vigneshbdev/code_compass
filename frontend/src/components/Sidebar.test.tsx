// FR-006 codebase list, FR-007 delete, U1 re-ingest badge (tasks T058, T139).
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Codebase } from "../api/client";
import { CodebaseList } from "./Sidebar";

function cb(id: string, overrides: Partial<Codebase> = {}): Codebase {
  return {
    id,
    name: `repo-${id}`,
    source_type: "zip",
    source_url: null,
    source_ref: null,
    commit_sha: null,
    status: "ready",
    error: null,
    error_code: null,
    reingest_required: false,
    progress: null,
    summary: null,
    created_at: "2026-11-16T10:00:00Z",
    updated_at: "2026-11-16T10:00:00Z",
    ...overrides,
  };
}

const noop = () => {};

describe("CodebaseList", () => {
  it("lists codebases with status and marks the selected one", () => {
    render(
      <CodebaseList
        codebases={[cb("a"), cb("b", { status: "ingesting" })]}
        selectedId="a"
        onSelect={noop}
        onDelete={noop}
        onReingest={noop}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByRole("button", { name: "repo-a" })).toHaveAttribute("aria-current", "true");
    expect(within(items[1]).getByText(/ingesting/i)).toBeInTheDocument();
  });

  it("selects a codebase with the keyboard", async () => {
    const onSelect = vi.fn();
    render(<CodebaseList codebases={[cb("a")]} selectedId={null} onSelect={onSelect} onDelete={noop} onReingest={noop} />);
    screen.getByRole("button", { name: "repo-a" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("a");
  });

  it("asks for confirmation before deleting", async () => {
    const onDelete = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<CodebaseList codebases={[cb("a")]} selectedId={null} onSelect={noop} onDelete={onDelete} onReingest={noop} />);
    const del = screen.getByRole("button", { name: /delete repo-a/i });
    await userEvent.click(del);
    expect(onDelete).not.toHaveBeenCalled();
    await userEvent.click(del);
    expect(onDelete).toHaveBeenCalledWith("a");
    confirm.mockRestore();
  });

  it("disables delete while ingesting", () => {
    render(<CodebaseList codebases={[cb("a", { status: "ingesting" })]} selectedId={null} onSelect={noop} onDelete={noop} onReingest={noop} />);
    expect(screen.getByRole("button", { name: /delete repo-a/i })).toBeDisabled();
  });

  it("shows a re-ingest badge and action when the embedding model changed (U1)", async () => {
    const onReingest = vi.fn();
    render(
      <CodebaseList codebases={[cb("a", { reingest_required: true })]} selectedId={null} onSelect={noop} onDelete={noop} onReingest={onReingest} />,
    );
    expect(screen.getByText(/re-ingest required/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /re-ingest repo-a/i }));
    expect(onReingest).toHaveBeenCalledWith("a");
  });
});
