/** Polls document status while UPLOADED/PROCESSING until READY/FAILED.
 *  The backend must never report READY before indexing succeeds, so the UI
 *  trusts only the status endpoint (App Flow 03). */

import { useEffect } from "react";
import { api } from "../api/client";
import { useAppStore } from "../store/useAppStore";

const POLL_MS = 1500;

export function useDocumentPolling(): void {
  const document = useAppStore((s) => s.document);
  const uploadPhase = useAppStore((s) => s.uploadPhase);
  const applyStatusUpdate = useAppStore((s) => s.applyStatusUpdate);

  useEffect(() => {
    if (!document) return;
    if (uploadPhase !== "PROCESSING" && uploadPhase !== "UPLOADING") return;

    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const status = await api.getDocumentStatus(document.documentId);
        if (cancelled) return;
        applyStatusUpdate(
          {
            documentId: status.document_id,
            filename: document.filename,
            status: status.status,
            pageCount: status.page_count,
            errorCode: status.error_code,
          },
          status.stage,
        );
        if (status.status === "READY" || status.status === "FAILED") return;
      } catch {
        /* transient network errors: keep polling */
      }
      if (!cancelled) {
        timer = window.setTimeout(poll, POLL_MS);
      }
    };

    timer = window.setTimeout(poll, POLL_MS);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [document, uploadPhase, applyStatusUpdate]);
}
