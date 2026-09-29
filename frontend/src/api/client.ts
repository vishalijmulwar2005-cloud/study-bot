/** Typed API client for the canonical /api/v1 contract.
 *
 *  Uses same-origin requests (the Vite dev server proxies /api to the
 *  backend), so the HttpOnly anonymous session cookie is always first-party.
 *  Set VITE_API_BASE_URL to call a different origin directly.
 */

import type {
  AskResponse,
  DocumentResponse,
  DocumentStatusResponse,
  Message,
  UploadResponse,
} from "../types";

const BASE = import.meta.env.VITE_API_BASE_URL || "";

export class ApiClientError extends Error {
  constructor(
    public code: string,
    message: string,
    public httpStatus: number,
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

async function parseError(response: Response): Promise<ApiClientError> {
  try {
    const body = await response.json();
    const err = body?.error;
    if (err?.code && err?.message) {
      return new ApiClientError(err.code, err.message, response.status);
    }
  } catch {
    /* fall through to generic */
  }
  return new ApiClientError(
    "INTERNAL_ERROR",
    "Something went wrong. Please try again.",
    response.status,
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as T;
}

export interface DocumentMeta {
  documentId: string;
  filename: string;
  status: DocumentResponse["status"];
  pageCount: number | null;
  errorCode: string | null;
}

function toMeta(dto: DocumentResponse): DocumentMeta {
  return {
    documentId: dto.document_id,
    filename: dto.filename,
    status: dto.status,
    pageCount: dto.page_count,
    errorCode: dto.error_code,
  };
}

export const api = {
  async uploadDocument(
    file: File,
    onProgress?: (fraction: number) => void,
    signal?: AbortSignal,
  ): Promise<UploadResponse> {
    // XHR (not fetch) for upload progress events (UX-03: visible progress).
    return new Promise<UploadResponse>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/api/v1/documents`);
      xhr.withCredentials = true;
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress(event.loaded / event.total);
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText) as UploadResponse);
        } else {
          let code = "INTERNAL_ERROR";
          let message = "Something went wrong. Please try again.";
          try {
            const body = JSON.parse(xhr.responseText);
            if (body?.error) {
              code = body.error.code;
              message = body.error.message;
            }
          } catch {
            /* generic error retained */
          }
          reject(new ApiClientError(code, message, xhr.status));
        }
      };
      xhr.onerror = () =>
        reject(
          new ApiClientError(
            "INTERNAL_ERROR",
            "Network error during upload. Please try again.",
            0,
          ),
        );
      xhr.onabort = () =>
        reject(new ApiClientError("INVALID_REQUEST", "Upload cancelled.", 0));
      signal?.addEventListener("abort", () => xhr.abort());
      const form = new FormData();
      form.append("file", file, file.name);
      xhr.send(form);
    });
  },

  async getDocument(documentId: string): Promise<DocumentMeta> {
    const dto = await request<DocumentResponse>(
      `/api/v1/documents/${documentId}`,
    );
    return toMeta(dto);
  },

  async getDocumentStatus(
    documentId: string,
  ): Promise<DocumentStatusResponse> {
    return request<DocumentStatusResponse>(
      `/api/v1/documents/${documentId}/status`,
    );
  },

  async retryDocument(documentId: string): Promise<DocumentStatusResponse> {
    return request<DocumentStatusResponse>(
      `/api/v1/documents/${documentId}/retry`,
      { method: "POST" },
    );
  },

  async deleteDocument(documentId: string): Promise<void> {
    await request<{ status: string }>(`/api/v1/documents/${documentId}`, {
      method: "DELETE",
    });
  },

  async createSession(documentId: string): Promise<string> {
    const dto = await request<{ session_id: string; document_id: string }>(
      "/api/v1/sessions",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: documentId }),
      },
    );
    return dto.session_id;
  },

  async listMessages(sessionId: string): Promise<Message[]> {
    const dto = await request<{ messages: Message[] }>(
      `/api/v1/sessions/${sessionId}/messages`,
    );
    return dto.messages;
  },

  async ask(sessionId: string, question: string): Promise<AskResponse> {
    return request<AskResponse>(`/api/v1/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  },

  async sendFeedback(messageId: string, rating: "up" | "down"): Promise<void> {
    await request(`/api/v1/messages/${messageId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating }),
    });
  },
};
