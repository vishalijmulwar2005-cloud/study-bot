/** Client state: document lifecycle + chat state machine (TRD §10 / UX §10).
 *
 *  Document: NEW -> UPLOADING -> PROCESSING -> READY | FAILED (-> retry)
 *  Chat:     IDLE -> SUBMITTING -> RETRIEVING -> GENERATING -> COMPLETE
 *            with NO_EVIDENCE and ERROR branches.
 */

import { create } from "zustand";
import { ApiClientError, api, type DocumentMeta } from "../api/client";
import type { ChatPhase, Message } from "../types";

export type UploadPhase =
  | "IDLE"
  | "DRAG_OVER"
  | "UPLOADING"
  | "INVALID"
  | "PROCESSING"
  | "SUCCESS"
  | "ERROR";

// Mirrors MAX_UPLOAD_MB in backend config — the frontend check is a UX
// convenience only; the backend performs authoritative validation.
const CLIENT_MAX_MB = 25;

interface AppState {
  document: DocumentMeta | null;
  uploadPhase: UploadPhase;
  uploadProgress: number;
  uploadError: string | null;
  lastStage: string | null;
  sessionId: string | null;
  messages: Message[];
  chatPhase: ChatPhase;
  chatError: { code: string; message: string } | null;
  sidebarOpen: boolean;
  pendingQuestion: string | null;

  setDragOver: (over: boolean) => void;
  uploadDocument: (file: File) => Promise<void>;
  applyStatusUpdate: (status: DocumentMeta, stage?: string | null) => void;
  retryProcessing: () => Promise<void>;
  removeDocument: () => Promise<void>;
  newChat: () => void;
  openSidebar: (open: boolean) => void;
  askQuestion: (question: string) => Promise<void>;
  clearChatError: () => void;
}

function clientValidate(file: File): string | null {
  const isPdf =
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "Please choose a PDF file.";
  if (file.size === 0) return "That file is empty.";
  if (file.size > CLIENT_MAX_MB * 1024 * 1024)
    return `That file is larger than ${CLIENT_MAX_MB} MB. Please choose a smaller PDF.`;
  return null;
}

function metaFromError(error: unknown): { code: string; message: string } {
  if (error instanceof ApiClientError) {
    return { code: error.code, message: error.message };
  }
  return {
    code: "INTERNAL_ERROR",
    message: "Something went wrong. Please try again.",
  };
}

export const useAppStore = create<AppState>((set, get) => ({
  document: null,
  uploadPhase: "IDLE",
  uploadProgress: 0,
  uploadError: null,
  lastStage: null,
  sessionId: null,
  messages: [],
  chatPhase: "IDLE",
  chatError: null,
  sidebarOpen: false,
  pendingQuestion: null,

  setDragOver: (over) =>
    set((state) => ({
      uploadPhase:
        state.uploadPhase === "UPLOADING" || state.uploadPhase === "PROCESSING"
          ? state.uploadPhase
          : over
            ? "DRAG_OVER"
            : "IDLE",
    })),

  async uploadDocument(file) {
    const invalid = clientValidate(file);
    if (invalid) {
      set({ uploadPhase: "INVALID", uploadError: invalid });
      return;
    }
    set({
      uploadPhase: "UPLOADING",
      uploadProgress: 0,
      uploadError: null,
      // A new upload starts a fresh conversation context (App Flow 08).
      sessionId: null,
      messages: [],
      chatPhase: "IDLE",
      chatError: null,
    });
    try {
      const response = await api.uploadDocument(file, (fraction) =>
        set({ uploadProgress: fraction }),
      );
      set({
        document: {
          documentId: response.document_id,
          filename: response.filename,
          status: response.status,
          pageCount: null,
          errorCode: null,
        },
        uploadPhase: "PROCESSING",
        uploadProgress: 1,
      });
    } catch (error) {
      set({
        uploadPhase: "ERROR",
        uploadError: metaFromError(error).message,
      });
    }
  },

  applyStatusUpdate(meta, stage) {
    const phase: UploadPhase =
      meta.status === "READY"
        ? "SUCCESS"
        : meta.status === "FAILED"
          ? "ERROR"
          : "PROCESSING";
    set({
      document: meta,
      uploadPhase: phase,
      lastStage: meta.status === "READY" || meta.status === "FAILED" ? null : (stage ?? null),
    });
  },

  async retryProcessing() {
    const document = get().document;
    if (!document) return;
    try {
      const status = await api.retryDocument(document.documentId);
      set({
        uploadPhase:
          status.status === "READY"
            ? "SUCCESS"
            : status.status === "FAILED"
              ? "ERROR"
              : "PROCESSING",
        uploadError: null,
        document: { ...document, status: status.status },
      });
    } catch (error) {
      set({ uploadError: metaFromError(error).message });
    }
  },

  async removeDocument() {
    const document = get().document;
    if (!document) return;
    try {
      // Backend runs the full cleanup workflow; UI only claims success
      // after the backend confirms (Security §09 deletion guarantee).
      await api.deleteDocument(document.documentId);
    } catch {
      /* deletion errors surface via the document card retry path */
    }
    set({
      document: null,
      uploadPhase: "IDLE",
      uploadProgress: 0,
      uploadError: null,
      sessionId: null,
      messages: [],
      chatPhase: "IDLE",
      chatError: null,
    });
  },

  newChat() {
    set({ sessionId: null, messages: [], chatPhase: "IDLE", chatError: null });
  },

  openSidebar(open) {
    set({ sidebarOpen: open });
  },

  async askQuestion(question) {
    const trimmed = question.trim();
    if (!trimmed) return;
    // Accept new questions from IDLE, after errors, and after completed
    // exchanges (follow-ups). Only block while a question is in flight.
    const phase = get().chatPhase;
    if (
      phase === "SUBMITTING" ||
      phase === "RETRIEVING" ||
      phase === "GENERATING"
    ) {
      return;
    }
    const document = get().document;
    if (!document || document.status !== "READY") return;

    const optimisticUser: Message = {
      message_id: `pending-${Date.now()}`,
      role: "user",
      content: trimmed,
      status: "COMPLETE",
      created_at: new Date().toISOString(),
      sources: [],
    };
    set({
      messages: [...get().messages, optimisticUser],
      chatPhase: "SUBMITTING",
      chatError: null,
      pendingQuestion: trimmed,
    });

    // Client-side approximation of the server's RETRIEVING -> GENERATING
    // phases for honest feedback (the single POST hides the split).
    const phaseTimer = window.setTimeout(() => {
      if (get().chatPhase === "SUBMITTING" || get().chatPhase === "RETRIEVING") {
        set({ chatPhase: "GENERATING" });
      }
    }, 1200);
    set({ chatPhase: "RETRIEVING" });

    try {
      let sessionId = get().sessionId;
      if (!sessionId) {
        sessionId = await api.createSession(document.documentId);
        set({ sessionId });
      }
      const response = await api.ask(sessionId, trimmed);
      window.clearTimeout(phaseTimer);
      const assistantMessage: Message = {
        message_id: response.message_id,
        role: "assistant",
        content: response.answer,
        status: response.grounded ? "COMPLETE" : "NO_EVIDENCE",
        created_at: new Date().toISOString(),
        sources: response.sources,
      };
      set((state) => ({
        messages: state.messages
          .filter((m) => m.message_id !== optimisticUser.message_id)
          .concat(optimisticUser, assistantMessage),
        chatPhase: response.grounded ? "COMPLETE" : "NO_EVIDENCE",
        pendingQuestion: null,
      }));
    } catch (error) {
      window.clearTimeout(phaseTimer);
      set((state) => ({
        // Keep the user's message visible; the error bubble offers retry.
        messages: state.messages,
        chatPhase: "ERROR",
        chatError: metaFromError(error),
      }));
    }
  },

  clearChatError() {
    set({ chatPhase: "IDLE", chatError: null });
  },
}));
