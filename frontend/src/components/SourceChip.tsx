import type { Source } from "../types";

/** Page/section chip under a grounded answer. Labels come exclusively from
 *  server-validated metadata (Phase 10) — never from model text.
 *  Source preview is intentionally not implemented (docs/DECISIONS.md #10). */
export function SourceChip({ source }: { source: Source }) {
  return (
    <span
      title={`Evidence from this page (match ${Math.round(source.relevance_score * 100)}%)`}
      className="border-line bg-surface text-ink-muted hover:border-primary-soft hover:text-primary inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors"
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 16 16"
        className="h-3 w-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      >
        <path d="M4 1.5h5.5L13 5v9.5H4z" strokeLinejoin="round" />
        <path d="M9.5 1.5V5H13" strokeLinejoin="round" />
      </svg>
      Page {source.page}
    </span>
  );
}
