// Citations in answers (FR-011, task T144): [path:start-end] → clickable references.
import type { CitationRef } from "../api/client";

const CITATION = /\[([\w./-]+):(\d+)(?:-(\d+))?\](?!\()/g;
const CODE_SPAN = /(`[^`]*`)/g;

/** Rewrites citations as markdown links with a `#cite:` fragment, skipping code spans. */
export function citationsToLinks(markdown: string): string {
  return markdown
    .split(CODE_SPAN)
    .map((part) =>
      part.startsWith("`")
        ? part
        : part.replace(CITATION, (_m, path: string, start: string, end?: string) =>
            `[${path}:${start}${end ? `-${end}` : ""}](#cite:${path}:${start}:${end ?? start})`,
          ),
    )
    .join("");
}

export function parseCiteHref(href: string | undefined): CitationRef | null {
  const match = href?.match(/^#cite:(.+):(\d+):(\d+)$/);
  if (!match) return null;
  return { path: match[1], start_line: Number(match[2]), end_line: Number(match[3]) };
}
