// NFR-007: clear in-UI message when the LLM key or database is broken (task T029).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Health } from "../api/client";
import { HealthBanner, isBlocking } from "./HealthBanner";

const ok: Health = {
  status: "ok",
  llm: "ok",
  database: "ok",
  langfuse: "ok",
  llm_help_url: "https://example.test/readme#get-a-free-gemini-key",
  langfuse_ui_url: "http://localhost:3000",
  version: "0.1.0",
};

describe("HealthBanner", () => {
  it("renders nothing when every component is ok", () => {
    const { container } = render(<HealthBanner health={ok} />);
    expect(container).toBeEmptyDOMElement();
    expect(isBlocking(ok)).toBe(false);
  });

  it.each(["missing", "invalid", "unreachable"] as const)(
    "blocks with a key help link when the LLM is %s",
    (llm) => {
      const health = { ...ok, llm, status: "degraded" as const };
      render(<HealthBanner health={health} />);
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent(/LLM/i);
      expect(screen.getByRole("link", { name: /free gemini key/i })).toHaveAttribute(
        "href",
        ok.llm_help_url,
      );
      expect(isBlocking(health)).toBe(true);
    },
  );

  it("names the README section when no help URL is configured", () => {
    render(<HealthBanner health={{ ...ok, llm: "missing", status: "degraded", llm_help_url: "" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/README.*Get a free Gemini key/);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("blocks when the database is unreachable", () => {
    const health = { ...ok, database: "unreachable" as const, status: "degraded" as const };
    render(<HealthBanner health={health} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/database/i);
    expect(isBlocking(health)).toBe(true);
  });

  it("shows a non-blocking warning when Langfuse is unreachable", () => {
    const health = { ...ok, langfuse: "unreachable" as const, status: "degraded" as const };
    render(<HealthBanner health={health} />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(/tracing/i);
    expect(isBlocking(health)).toBe(false);
  });
});
