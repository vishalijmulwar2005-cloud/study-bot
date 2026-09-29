import { useEffect, useRef } from "react";
import { useAppStore } from "../store/useAppStore";
import { ErrorState } from "./ErrorState";
import { LoadingState } from "./LoadingState";
import { MessageBubble } from "./MessageBubble";
import { SuggestedPrompt } from "./SuggestedPrompt";

/** Chat workspace: the visual focus. Centered column, generous rhythm,
 *  polished welcome state. */

const SUGGESTIONS = ["Summarize this PDF", "Explain the main topics", "Give me the key points"];

function WelcomeChat() {
  const chatPhase = useAppStore((s) => s.chatPhase);
  const askQuestion = useAppStore((s) => s.askQuestion);
  const disabled = chatPhase !== "IDLE";
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-4 py-10 text-center">
      <span
        aria-hidden="true"
        className="from-primary to-primary-deep shadow-pop flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br text-xl text-white"
      >
        ✦
      </span>
      <div>
        <h1 className="text-2xl font-semibold tracking-[-0.02em]">
          Ask anything from your PDF
        </h1>
        <p className="text-ink-muted mx-auto mt-2 max-w-md text-[15px] leading-relaxed">
          Answers are based on your uploaded document. If something isn't in
          it, StudyBot will say so.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((suggestion) => (
          <SuggestedPrompt
            key={suggestion}
            label={suggestion}
            disabled={disabled}
            onClick={() => void askQuestion(suggestion)}
          />
        ))}
      </div>
    </div>
  );
}

export function ChatWindow() {
  const messages = useAppStore((s) => s.messages);
  const chatPhase = useAppStore((s) => s.chatPhase);
  const chatError = useAppStore((s) => s.chatError);
  const clearChatError = useAppStore((s) => s.clearChatError);
  const pendingQuestion = useAppStore((s) => s.pendingQuestion);
  const askQuestion = useAppStore((s) => s.askQuestion);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, chatPhase]);

  return (
    <div className="chat-scroll flex-1 overflow-y-auto px-4 py-6 sm:px-8">
      <div className="mx-auto flex max-w-3xl flex-col gap-5">
        {messages.length === 0 && chatPhase === "IDLE" && <WelcomeChat />}

        {messages.map((message) => (
          <MessageBubble key={message.message_id} message={message} />
        ))}

        {(chatPhase === "RETRIEVING" ||
          chatPhase === "GENERATING" ||
          chatPhase === "SUBMITTING") && <LoadingState phase={chatPhase} />}

        {chatPhase === "ERROR" && chatError && (
          <div className="max-w-[92%] sm:max-w-[76%]">
            <ErrorState
              message={chatError.message}
              retryLabel="Retry question"
              onRetry={() => {
                clearChatError();
                if (pendingQuestion) void askQuestion(pendingQuestion);
              }}
            />
          </div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}
