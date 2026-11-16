// FR-010: parse server-sent events from a POST response stream (task T144).
import { describe, expect, it } from "vitest";
import { SseParser } from "./sse";

describe("SseParser", () => {
  it("parses complete frames", () => {
    const p = new SseParser();
    const events = p.push('event: meta\ndata: {"trace_id":"t1"}\n\nevent: token\ndata: {"text":"Hi"}\n\n');
    expect(events).toEqual([
      { event: "meta", data: { trace_id: "t1" } },
      { event: "token", data: { text: "Hi" } },
    ]);
  });

  it("handles frames split across reads", () => {
    const p = new SseParser();
    expect(p.push("event: tok")).toEqual([]);
    expect(p.push('en\ndata: {"text":"a')).toEqual([]);
    expect(p.push('b"}\n\nevent: done\ndata: {"status":"complete"}\n')).toEqual([
      { event: "token", data: { text: "ab" } },
    ]);
    expect(p.push("\n")).toEqual([{ event: "done", data: { status: "complete" } }]);
  });

  it("ignores malformed frames instead of throwing", () => {
    const p = new SseParser();
    expect(p.push("data: not json\n\nevent: token\ndata: {\"text\":\"ok\"}\n\n")).toEqual([
      { event: "token", data: { text: "ok" } },
    ]);
  });
});
