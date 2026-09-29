import { useCallback, useRef, useState, type DragEvent } from "react";
import { useAppStore } from "../store/useAppStore";

/** Premium upload experience: calm hero empty-state with a soft drop zone.
 *  Accessible: labeled file input, keyboard reachable, aria-live feedback. */

export function UploadZone() {
  const uploadPhase = useAppStore((s) => s.uploadPhase);
  const uploadProgress = useAppStore((s) => s.uploadProgress);
  const uploadError = useAppStore((s) => s.uploadError);
  const uploadDocument = useAppStore((s) => s.uploadDocument);
  const setDragOver = useAppStore((s) => s.setDragOver);
  const inputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  const busy = uploadPhase === "UPLOADING" || uploadPhase === "PROCESSING";

  const pick = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (!file) return;
      setFileName(file.name);
      void uploadDocument(file);
    },
    [uploadDocument],
  );

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragOver(false);
    if (!busy) pick(event.dataTransfer.files);
  };

  const progressPct = Math.round(uploadProgress * 100);

  return (
    <div className="animate-fade-up w-full max-w-xl">
      <div className="mb-7 flex flex-col items-center text-center">
        <span
          aria-hidden="true"
          className="from-primary to-primary-deep mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br text-2xl text-white shadow-pop"
        >
          ✦
        </span>
        <h1 className="text-[26px] font-semibold tracking-[-0.02em] sm:text-3xl">
          Upload a PDF to start asking questions
        </h1>
        <p className="text-ink-muted mt-2.5 max-w-md text-[15px] leading-relaxed">
          Answers are grounded only in your uploaded document — with page
          references you can verify.
        </p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center gap-4 rounded-2xl border-2 border-dashed px-6 py-9 text-center transition-all duration-200 ${
          uploadPhase === "DRAG_OVER"
            ? "border-primary bg-primary-subtle/70 scale-[1.01]"
            : "border-line bg-surface/60 hover:border-primary-soft"
        }`}
      >
        <input
          ref={inputRef}
          id="pdf-upload-input"
          type="file"
          accept="application/pdf,.pdf"
          className="sr-only"
          onChange={(e) => pick(e.target.files)}
          disabled={busy}
        />
        <label
          htmlFor="pdf-upload-input"
          className={`inline-flex cursor-pointer items-center gap-2 rounded-full px-6 py-3 text-sm font-semibold transition-all duration-150 ${
            busy
              ? "text-ink-muted bg-ink-muted/15 cursor-not-allowed"
              : "bg-primary hover:bg-primary-deep text-white shadow-pop hover:-translate-y-px"
          }`}
        >
          {busy ? "Working…" : "Choose a PDF"}
        </label>
        <p className="text-ink-faint text-xs">or drag &amp; drop it here · PDF only · up to 25 MB</p>

        {uploadPhase === "UPLOADING" && (
          <div className="mt-1 w-full max-w-sm" aria-live="polite">
            <div className="text-ink-muted mb-1.5 flex justify-between text-xs">
              <span className="truncate">{fileName ?? "Uploading…"}</span>
              <span className="font-medium">{progressPct}%</span>
            </div>
            <div
              className="bg-line h-1.5 w-full overflow-hidden rounded-full"
              role="progressbar"
              aria-valuenow={progressPct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Upload progress"
            >
              <div
                className="from-primary to-primary-soft h-full rounded-full bg-gradient-to-r transition-all duration-200"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        )}

        {(uploadPhase === "INVALID" || uploadPhase === "ERROR") && uploadError && (
          <p role="alert" className="text-sm font-medium text-danger">
            {uploadError}
          </p>
        )}
      </div>

      {uploadPhase !== "UPLOADING" && uploadPhase !== "PROCESSING" && (
        <p className="sr-only" aria-live="polite">
          {uploadError ?? ""}
        </p>
      )}
    </div>
  );
}
