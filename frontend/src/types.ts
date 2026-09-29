/** Shared types mirroring the backend API contract (schemas.py). */

export type DocumentStatus =
  | "UPLOADED"
  | "PROCESSING"
  | "READY"
  | "FAILED"
  | "DELETING"
  | "DELETED";

export type JobStage = "QUEUED" | "EXTRACT" | "CHUNK" | "EMBED" | "INDEX" | "DONE";

export interface UploadResponse {
  document_id: string;
  status: DocumentStatus;
  filename: string;
  processing_job_id: string;
}

export interface DocumentStatusResponse {
  document_id: string;
  status: DocumentStatus;
  stage: JobStage | null;
  page_count: number | null;
  error_code: string | null;
}

export interface DocumentResponse {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  page_count: number | null;
  error_code: string | null;
  created_at: string;
}

export interface Source {
  chunk_id: string;
  page: number;
  relevance_score: number;
}

export interface Message {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  status: "COMPLETE" | "NO_EVIDENCE" | "ERROR";
  created_at: string;
  sources: Source[];
}

export interface AskResponse {
  message_id: string;
  answer: string;
  grounded: boolean;
  sources: Source[];
}

export interface ApiErrorBody {
  code: string;
  message: string;
}

/** Client-side chat state machine (UI/UX spec §10, TRD §10). */
export type ChatPhase =
  | "IDLE"
  | "SUBMITTING"
  | "RETRIEVING"
  | "GENERATING"
  | "COMPLETE"
  | "NO_EVIDENCE"
  | "ERROR";
