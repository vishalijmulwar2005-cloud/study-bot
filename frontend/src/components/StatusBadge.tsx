import type { DocumentStatus } from "../types";

/** Status pill: icon + text + subtle color — never color alone (UI/UX §5/§9). */

const STYLES: Record<string, { label: string; className: string; dot: string; check?: boolean }> = {
  UPLOADED: { label: "Uploaded", className: "bg-primary-subtle text-primary-deep", dot: "bg-primary-soft" },
  PROCESSING: { label: "Processing", className: "bg-primary-subtle text-primary-deep", dot: "bg-primary animate-pulse" },
  READY: { label: "Ready", className: "bg-emerald-50 text-success", dot: "bg-success", check: true },
  FAILED: { label: "Failed", className: "bg-red-50 text-danger", dot: "bg-danger" },
  DELETING: { label: "Deleting", className: "bg-background text-ink-muted", dot: "bg-ink-faint animate-pulse" },
  DELETED: { label: "Deleted", className: "bg-background text-ink-muted", dot: "bg-ink-faint" },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const style = STYLES[status] ?? STYLES.PROCESSING;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${style.className}`}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {style.check ? (
        <svg aria-hidden="true" viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 8.5 6.5 12 13 4.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : null}
      {style.label}
    </span>
  );
}
