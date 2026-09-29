import { useAppStore } from "../store/useAppStore";
import { StatusBadge } from "./StatusBadge";
import { Composer } from "./Composer";
import { DocumentCard } from "./DocumentCard";
import { UploadZone } from "./UploadZone";
import { ChatWindow } from "./ChatWindow";

/** Application shell: top navigation (brand · active document · status) +
 *  sidebar + chat workspace + floating composer. Document scope is never
 *  fully hidden (UI/UX §8 responsive hierarchy: PDF → conversation → composer). */

function BrandMark() {
  return (
    <span
      aria-hidden="true"
      className="from-primary to-primary-deep shadow-pop flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br text-sm text-white"
    >
      ✦
    </span>
  );
}

export function AppShell() {
  const document = useAppStore((s) => s.document);
  const uploadPhase = useAppStore((s) => s.uploadPhase);
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const openSidebar = useAppStore((s) => s.openSidebar);
  const showWorkspace =
    document !== null &&
    (uploadPhase === "PROCESSING" ||
      uploadPhase === "SUCCESS" ||
      uploadPhase === "ERROR" ||
      document.status === "DELETING");

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col">
      {/* Top navigation: brand · active document · status */}
      <header className="border-lineSoft bg-surface/70 border-b px-4 backdrop-blur-md sm:px-6">
        <div className="flex h-14 items-center gap-3">
          <button
            type="button"
            onClick={() => openSidebar(!sidebarOpen)}
            aria-label={sidebarOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={sidebarOpen}
            className="text-ink-muted hover:bg-background rounded-lg p-2 transition-colors md:hidden"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
            </svg>
          </button>

          <div className="flex items-center gap-2.5">
            <BrandMark />
            <p className="hidden text-sm font-semibold tracking-[-0.01em] sm:block">
              StudyBot
            </p>
          </div>

          <div className="mx-1 h-5 w-px bg-line" aria-hidden="true" />

          {document ? (
            <div className="flex min-w-0 items-center gap-2.5">
              <p className="text-ink-muted max-w-[38vw] truncate text-sm sm:max-w-xs">
                {document.filename}
              </p>
              <StatusBadge status={document.status} />
            </div>
          ) : (
            <p className="text-ink-faint text-sm">No document</p>
          )}
        </div>
      </header>

      {showWorkspace ? (
        <>
          <div className="px-4 pt-5 sm:px-8">
            <div className="mx-auto max-w-3xl">
              <DocumentCardWithStage />
            </div>
          </div>
          {document?.status === "READY" ? (
            <>
              <ChatWindow />
              <Composer />
            </>
          ) : (
            <ProcessingPanel />
          )}
        </>
      ) : (
        <div className="flex flex-1 items-center justify-center px-4 pb-12">
          <UploadZone />
        </div>
      )}
    </div>
  );
}

function DocumentCardWithStage() {
  const lastStage = useAppStore((s) => s.lastStage);
  return <DocumentCard stage={lastStage} />;
}

function ProcessingPanel() {
  const status = useAppStore((s) => s.document?.status);
  if (status === "FAILED") {
    return (
      <div className="text-ink-muted flex flex-1 items-center justify-center px-4 text-sm">
        Resolve the issue on the document card above, then try again.
      </div>
    );
  }
  return (
    <div className="flex flex-1 items-center justify-center px-4 pb-16">
      <div
        role="status"
        aria-live="polite"
        className="text-ink-muted flex flex-col items-center gap-4 text-sm"
      >
        <span className="relative flex h-10 w-10 items-center justify-center">
          <span
            aria-hidden="true"
            className="border-line border-t-primary absolute inset-0 animate-spin rounded-full border-2"
          />
          <span aria-hidden="true" className="text-primary text-xs">
            ▣
          </span>
        </span>
        Reading your PDF — the composer unlocks when the document is ready.
      </div>
    </div>
  );
}
