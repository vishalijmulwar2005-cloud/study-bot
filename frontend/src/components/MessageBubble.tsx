import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Message, Source } from "../types";
import { api } from "../api/client";
import { SourceChip } from "./SourceChip";

/** Message presentation: user = compact primary bubble; assistant = calm
 *  open surface with a subtle identity mark (no heavy cards). Markdown only
 *  (raw HTML never rendered), server-validated source chips, copy + feedback.
 *  No-evidence is a normal assistant response, never error styling. */

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard unavailable — non-critical */
        }
      }}
      className="text-ink-faint hover:bg-background hover:text-ink rounded-full px-2 py-1 text-[11px] font-medium transition-colors"
      aria-label={copied ? "Copied" : "Copy answer"}
    >
      {copied ? "Copied ✓" : "Copy"}
    </button>
  );
}

function FeedbackButtons({ messageId }: { messageId: string }) {
  const [sent, setSent] = useState<"up" | "down" | null>(null);
  const send = (rating: "up" | "down") => {
    if (sent) return;
    setSent(rating);
    void api.sendFeedback(messageId, rating).catch(() => setSent(null));
  };
  return (
    <span className="flex items-center gap-0.5">
      <button
        type="button"
        onClick={() => send("up")}
        aria-label="Helpful answer"
        aria-pressed={sent === "up"}
        className={`hover:bg-background rounded-full px-1.5 py-1 text-xs transition-colors ${
          sent === "up" ? "text-success" : "text-ink-faint hover:text-success"
        }`}
      >
        👍
      </button>
      <button
        type="button"
        onClick={() => send("down")}
        aria-label="Not helpful"
        aria-pressed={sent === "down"}
        className={`hover:bg-background rounded-full px-1.5 py-1 text-xs transition-colors ${
          sent === "down" ? "text-danger" : "text-ink-faint hover:text-danger"
        }`}
      >
        👎
      </button>
    </span>
  );
}

function Sources({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  return (
    <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
      <span className="text-ink-faint text-[11px] font-semibold uppercase tracking-wide">
        Sources
      </span>
      {sources.map((source) => (
        <SourceChip key={source.chunk_id} source={source} />
      ))}
    </div>
  );
}

export function MessageBubble({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="animate-fade-up flex justify-end">
        <div className="bg-primary max-w-[85%] rounded-bubble rounded-br-md px-4 py-2.5 text-[15px] leading-relaxed text-white sm:max-w-[72%]">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    );
  }

  const noEvidence = message.status === "NO_EVIDENCE";
  const isPersisted = !message.message_id.startsWith("pending-");
  return (
    <div className="animate-fade-up flex justify-start gap-3">
      <span
        aria-hidden="true"
        className={`mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[11px] ${
          noEvidence
            ? "bg-background text-ink-faint"
            : "from-primary to-primary-deep bg-gradient-to-br text-white"
        }`}
      >
        ✦
      </span>
      <div className="min-w-0 max-w-[88%] sm:max-w-[76%]">
        <p className="text-ink-faint mb-1 text-[11px] font-semibold uppercase tracking-wide">
          StudyBot
        </p>
        <div
          className={`rounded-bubble rounded-bl-md px-4 py-3 ${
            noEvidence ? "bg-surface/70 ring-1 ring-lineSoft" : "bg-surface shadow-card ring-1 ring-lineSoft"
          }`}
        >
          <div className="answer-markdown">
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </div>
          {noEvidence && (
            <p className="text-ink-faint mt-2 border-line border-t pt-2 text-xs">
              Try asking about another section of the document.
            </p>
          )}
          <Sources sources={message.sources} />
        </div>
        {!noEvidence && isPersisted && (
          <div className="mt-0.5 flex items-center gap-0.5 pl-1">
            <CopyButton text={message.content} />
            <FeedbackButtons messageId={message.message_id} />
          </div>
        )}
      </div>
    </div>
  );
}
