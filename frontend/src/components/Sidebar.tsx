import { useAppStore } from "../store/useAppStore";
import { StatusBadge } from "./StatusBadge";

/** Sidebar: light navigation surface — New Chat, Documents (active card),
 *  Recent note. Collapses to a drawer below 768px; narrower on tablet. */

export function Sidebar() {
  const document = useAppStore((s) => s.document);
  const newChat = useAppStore((s) => s.newChat);
  const messages = useAppStore((s) => s.messages);
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const openSidebar = useAppStore((s) => s.openSidebar);

  const hasConversation = messages.length > 0;

  return (
    <>
      {/* Mobile scrim */}
      {sidebarOpen && (
        <div
          className="bg-ink/25 fixed inset-0 z-30 backdrop-blur-[2px] md:hidden"
          onClick={() => openSidebar(false)}
          aria-hidden="true"
        />
      )}

      <aside
        aria-label="Navigation sidebar"
        className={`border-line bg-surface/80 fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r backdrop-blur-md transition-transform duration-200 md:static md:z-auto md:w-60 md:translate-x-0 xl:w-72 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <nav className="flex flex-1 flex-col gap-1 px-3 pt-4">
          <button
            type="button"
            onClick={() => {
              newChat();
              openSidebar(false);
            }}
            disabled={!document || document.status !== "READY"}
            className="border-line text-ink hover:border-primary hover:text-primary hover:shadow-card mb-2 flex items-center gap-2.5 rounded-xl border bg-white px-3.5 py-2.5 text-sm font-semibold transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-line disabled:hover:text-ink disabled:hover:shadow-none"
          >
            <span aria-hidden="true" className="text-primary text-base leading-none">
              ＋
            </span>
            New Chat
          </button>

          <p className="text-ink-faint mt-2 px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider">
            Documents
          </p>
          {document ? (
            <div className="bg-primary-subtle/70 border-primary-soft/60 rounded-xl border px-3.5 py-3">
              <div className="flex items-center gap-2">
                <span aria-hidden="true" className="text-primary text-xs">
                  ▣
                </span>
                <p className="truncate text-sm font-semibold">{document.filename}</p>
              </div>
              <div className="mt-2">
                <StatusBadge status={document.status} />
              </div>
            </div>
          ) : (
            <p className="text-ink-faint mt-1 px-3.5 text-xs leading-relaxed">
              No document yet — upload one to begin.
            </p>
          )}

          <p className="text-ink-faint mt-5 px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider">
            Recent
          </p>
          {hasConversation ? (
            <div className="border-lineSoft rounded-xl border px-3.5 py-2.5">
              <p className="text-ink-muted truncate text-sm">
                Current conversation
              </p>
              <p className="text-ink-faint mt-0.5 text-[11px]">
                {messages.length} message{messages.length === 1 ? "" : "s"}
              </p>
            </div>
          ) : (
            <p className="text-ink-faint mt-1 px-3.5 text-xs leading-relaxed">
              Chat history is not persisted in the MVP.
            </p>
          )}
        </nav>

        <div className="border-lineSoft mt-4 border-t px-5 py-4">
          <p className="text-ink-faint flex items-start gap-2 text-[11px] leading-relaxed">
            <span aria-hidden="true" className="mt-px">
              ⛨
            </span>
            Answers come only from your uploaded PDF — never from outside
            knowledge.
          </p>
        </div>
      </aside>
    </>
  );
}
