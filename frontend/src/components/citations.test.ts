// FR-011: citations in answers become clickable references (task T144).
import { describe, expect, it } from "vitest";
import { citationsToLinks, parseCiteHref } from "./citations";

describe("citations", () => {
  it("turns [path:start-end] into markdown links with a cite fragment", () => {
    expect(citationsToLinks("See [app/core/config.py:8-17] and [a.py:3].")).toBe(
      "See [app/core/config.py:8-17](#cite:app/core/config.py:8:17) and [a.py:3](#cite:a.py:3:3).",
    );
  });

  it("leaves code spans and normal links alone", () => {
    const text = "Use `[x.py:1-2]` or [docs](https://example.test).";
    expect(citationsToLinks(text)).toBe(text);
  });

  it("parses cite hrefs back", () => {
    expect(parseCiteHref("#cite:app/core/config.py:8:17")).toEqual({
      path: "app/core/config.py",
      start_line: 8,
      end_line: 17,
    });
    expect(parseCiteHref("https://example.test")).toBeNull();
  });
});
