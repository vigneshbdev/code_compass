// Server-sent events over a POST response body (FR-010, task T144). EventSource only supports
// GET, so we read the stream ourselves and parse frames that may be split across reads.
export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

export class SseParser {
  private buffer = "";

  push(chunk: string): SseEvent[] {
    this.buffer += chunk;
    const events: SseEvent[] = [];
    let end: number;
    while ((end = this.buffer.indexOf("\n\n")) !== -1) {
      const frame = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      try {
        events.push({ event, data: JSON.parse(data) as Record<string, unknown> });
      } catch {
        // a malformed frame must not break the rest of the stream
      }
    }
    return events;
  }
}

export async function postSse(
  url: string,
  body: unknown,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    let message = `Request failed (${response.status})`;
    try {
      const err = (await response.json()) as { error?: { message?: string } };
      message = err.error?.message ?? message;
    } catch {
      // keep the generic message
    }
    throw new Error(message);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const event of parser.push(decoder.decode(value, { stream: true }))) onEvent(event);
  }
}
