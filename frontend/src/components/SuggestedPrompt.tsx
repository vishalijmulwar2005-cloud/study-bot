/** Quick-action pill (PRD 5.1). Inserts the question; does not bypass
 *  grounding — the backend evidence gate still applies. */

export function SuggestedPrompt({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="border-line bg-surface text-ink-muted hover:border-primary-soft hover:text-primary hover:shadow-card rounded-full border px-4 py-2 text-sm transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:shadow-none"
    >
      {label}
    </button>
  );
}
