// FR-012: the cited code is shown with line numbers and the cited lines highlighted (T144).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CodeView } from "./CodeViewer";

const content = Array.from({ length: 30 }, (_, i) => `line_${i + 1} = ${i + 1}`).join("\n");

describe("CodeView", () => {
  it("numbers lines and highlights the cited range", () => {
    render(<CodeView path="app/x.py" language="python" content={content} start={8} end={10} redactions={0} />);
    const highlighted = screen.getAllByTestId("line").filter((el) => el.dataset.highlighted === "true");
    expect(highlighted.map((el) => el.dataset.line)).toEqual(["8", "9", "10"]);
    expect(highlighted[1].textContent).toContain("line_9 = 9"); // tokens split across spans
  });

  it("shows how many secrets were redacted", () => {
    render(<CodeView path="settings.py" language="python" content={"KEY = '[REDACTED:stripe_key]'"} start={1} end={1} redactions={2} />);
    expect(screen.getByText(/2 secrets redacted/i)).toBeInTheDocument();
  });
});
