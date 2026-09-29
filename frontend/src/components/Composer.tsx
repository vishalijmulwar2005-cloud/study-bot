import { useState, type KeyboardEvent } from "react";
import { useAppStore } from "../store/useAppStore";

/** Floating premium composer: rounded container with depth, prominent but
 *  calm. Enabled only when the document is READY (Phase 15 rules). */

export function Composer() {
  const document = useAppStore((s) => s.document);
  const chatPhase = useAppStore((s) => s.chatPhase);
  const askQuestion = useAppStore((s) => s.askQuestion);
  const [value, setValue] = useState("");
  const [focused, setFocused] = useState(false);

  const busy =
    chatPhase === "SUBMITTING" ||
    chatPhase === "RETRIEVING" ||
    chatPhase === "GENERATING";
  const documentReady = document?.status === "READY";
  const enabled = documentReady && !busy;

  const submit = () => {
    const question = value.trim();
    if (!question || !enabled) return;
    setValue("");
    void askQuestion(question);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="pointer-events-none sticky bottom-0 z-10 px-4 pb-4 sm:px-8">
      <div className="pointer-events-none mx-auto max-w-3xl">
        {/* soft fade so messages glide behind the composer */}
        <div
          aria-hidden="true"
          className="pointer-events-none h-8 bg-gradient-to-t from-[#F7F8FA] to-transparent"
        />
        <div
          className={`pointer-events-auto flex items-end gap-2 rounded-2xl bg-white p-2 pl-4 transition-shadow duration-200 ${
            focused
              ? "shadow-float ring-2 ring-primary/70"
              : "shadow-card ring-1 ring-line"
          }`}
        >
          <label htmlFor="question-composer" className="sr-only">
            Ask a question about the active PDF
          </label>
          <textarea
            id="question-composer"
            rows={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            disabled={!enabled}
            placeholder={
              documentReady
                ? "Ask anything about this PDF…"
                : "Upload a PDF and wait until it's ready to ask questions"
            }
            className="placeholder:text-ink-faint max-h-40 min-h-[44px] flex-1 resize-none bg-transparent py-2.5 text-[15px] outline-none disabled:cursor-not-allowed disabled:opacity-60"
          />
          <button
            type="button"
            onClick={submit}
            disabled={!enabled || !value.trim()}
            aria-label="Send question"
            className="from-primary to-primary-deep shadow-pop hover:bg-primary-deep m-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br text-white transition-all duration-150 hover:-translate-y-px disabled:cursor-not-allowed disabled:from-line disabled:to-line disabled:shadow-none disabled:hover:translate-y-0"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="h-[18px] w-[18px]"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
            >
              <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
        <p className="text-ink-faint mt-1.5 text-center text-[11px]">
          Answers come only from the uploaded PDF · Enter to send · Shift+Enter
          for a new line
        </p>
      </div>
    </div>
  );
}
