/** Error presentation (FR-08 / UX-07): visually distinct from answers,
 *  always exactly one clear recovery action, never an infinite spinner. */

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}

export function ErrorState({
  message,
  onRetry,
  retryLabel = "Try again",
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="animate-fade-up border-danger/25 flex items-start gap-3 rounded-bubble border bg-red-50/70 p-4"
    >
      <span
        aria-hidden="true"
        className="bg-danger/10 text-danger mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
      >
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8">
          <circle cx="10" cy="10" r="7.5" />
          <path d="M10 6.5v4M10 13.2v.4" strokeLinecap="round" />
        </svg>
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm text-ink">{message}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="border-danger/30 text-danger hover:bg-danger hover:border-danger mt-2.5 rounded-full border px-3.5 py-1.5 text-xs font-semibold transition-colors"
          >
            {retryLabel}
          </button>
        )}
      </div>
    </div>
  );
}
