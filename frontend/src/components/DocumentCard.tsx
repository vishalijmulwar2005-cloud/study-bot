import { useAppStore } from "../store/useAppStore";
import { StatusBadge } from "./StatusBadge";

/** Elegant document card above the chat: icon tile, name + pages, status,
 *  retry/remove actions. */

const STAGE_COPY: Record<string, string> = {
  QUEUED: "Queued for processing…",
  EXTRACT: "Reading your PDF…",
  CHUNK: "Splitting into sections…",
  EMBED: "Building the search index…",
  INDEX: "Finishing up…",
  DONE: "Finishing up…",
};

export function DocumentCard({ stage }: { stage: string | null }) {
  const document = useAppStore((s) => s.document);
  const uploadPhase = useAppStore((s) => s.uploadPhase);
  const removeDocument = useAppStore((s) => s.removeDocument);
  const retryProcessing = useAppStore((s) => s.retryProcessing);

  if (!document) return null;

  const failed = document.status === "FAILED";
  const processing =
    document.status === "UPLOADED" || document.status === "PROCESSING";

  return (
    <section
      aria-label="Active document"
      className="card animate-fade-up flex items-center gap-3.5 p-3.5 sm:p-4"
    >
      <span
        aria-hidden="true"
        className="bg-primary-subtle text-primary flex h-11 w-11 shrink-0 items-center justify-center rounded-xl"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M13.5 3H6.75A1.75 1.75 0 0 0 5 4.75v14.5A1.75 1.75 0 0 0 6.75 21h10.5A1.75 1.75 0 0 0 19 19.25V8.5z" />
          <path d="M13.5 3v5.5H19" />
        </svg>
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{document.filename}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <StatusBadge status={document.status} />
          <span className="text-ink-faint text-xs" aria-live="polite">
            {processing && (STAGE_COPY[stage ?? ""] ?? "Processing your document…")}
            {document.status === "READY" &&
              `${document.pageCount ?? "?"} page${document.pageCount === 1 ? "" : "s"} · ready for questions`}
            {failed && friendlyProcessingError(document.errorCode)}
          </span>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        {failed && (
          <button
            type="button"
            onClick={() => void retryProcessing()}
            className="border-line text-ink hover:border-primary hover:text-primary rounded-full border px-3.5 py-1.5 text-xs font-semibold transition-colors"
          >
            Retry
          </button>
        )}
        <button
          type="button"
          onClick={() => void removeDocument()}
          disabled={uploadPhase === "UPLOADING"}
          className="border-line text-ink-muted hover:border-danger hover:text-danger rounded-full border px-3.5 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50"
        >
          {failed ? "Replace" : "Remove"}
        </button>
      </div>
    </section>
  );
}

function friendlyProcessingError(code: string | null): string {
  switch (code) {
    case "OCR_UNAVAILABLE":
      return "This PDF looks scanned (image-only). Upload a text-based PDF.";
    case "FILE_TOO_LARGE":
      return "The PDF exceeds the size limit. Try a smaller file.";
    case "EMPTY_DOCUMENT":
      return "No readable text found in this PDF.";
    case "EMBEDDING_NOT_CONFIGURED":
    case "STORAGE_UNAVAILABLE":
      return "A document service is unavailable. Contact the operator.";
    default:
      return "Processing failed. You can retry or upload a different PDF.";
  }
}
