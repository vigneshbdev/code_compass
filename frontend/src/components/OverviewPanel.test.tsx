// FR-020: overview shows languages and dependencies grouped by manifest (task T149).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OverviewPanel } from "./OverviewPanel";

describe("OverviewPanel", () => {
  it("lists languages and dependencies by manifest", () => {
    render(
      <OverviewPanel
        overview={{
          languages: [
            { language: "python", files: 120, lines: 9800 },
            { language: "typescript", files: 80, lines: 6000 },
          ],
          dependencies: [
            { manifest: "backend/pyproject.toml", ecosystem: "pypi", name: "fastapi", spec: ">=0.114", dev: false },
            { manifest: "frontend/package.json", ecosystem: "npm", name: "react", spec: "^18", dev: false },
          ],
          starter_questions: ["How is auth done?", "Where are routes?", "How do tests run?"],
          starter_source: "llm",
        }}
      />,
    );
    expect(screen.getByRole("cell", { name: "python" })).toBeInTheDocument();
    expect(screen.getByText("9,800")).toBeInTheDocument();
    expect(screen.getByText("backend/pyproject.toml")).toBeInTheDocument();
    expect(screen.getByText("react")).toBeInTheDocument();
  });
});
