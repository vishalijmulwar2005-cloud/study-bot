/** AI-response loading indicator: animated dots + progressive state label.
 *  Subtle by design; honors prefers-reduced-motion globally. */

const STEPS: Record<string, string> = {
  SUBMITTING: "Sending your question",
  RETRIEVING: "Searching your PDF",
  GENERATING: "Writing the answer",
};

export function LoadingState({ phase }: { phase: string }) {
  const label = STEPS[phase] ?? STEPS.RETRIEVING;
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-2.5 rounded-bubble rounded-bl-md bg-surface px-4 py-3 shadow-card ring-1 ring-lineSoft">
        <span
          className="bg-primary flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-[10px] text-white"
          aria-hidden="true"
        >
          ✦
        </span>
        <span className="flex gap-1" aria-hidden="true">
          <span className="bg-primary-soft h-1.5 w-1.5 animate-dot-bounce rounded-full [animation-delay:0ms]" />
          <span className="bg-primary-soft h-1.5 w-1.5 animate-dot-bounce rounded-full [animation-delay:150ms]" />
          <span className="bg-primary-soft h-1.5 w-1.5 animate-dot-bounce rounded-full [animation-delay:300ms]" />
        </span>
        <span
          role="status"
          aria-live="polite"
          className="text-ink-muted text-sm"
        >
          {label}…
        </span>
      </div>
    </div>
  );
}
