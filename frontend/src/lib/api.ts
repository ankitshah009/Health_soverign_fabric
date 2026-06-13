import {
  ClaimData,
  ApprovalRequest,
  DecisionReceipt,
  Evidence,
  AuditEntry,
  ChatEvent,
} from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchJSON<T>(
  url: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: {
      ...(options?.headers || {}),
    },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(
      `API Error ${res.status}: ${text}`
    );
  }

  return res.json() as Promise<T>;
}

export async function submitClaim(
  formData: FormData
): Promise<{ claim_id: string; status: string }> {
  const res = await fetch(`${BASE_URL}/api/claims/submit`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`Failed to submit claim: ${text}`);
  }

  return res.json();
}

export async function getClaim(id: string): Promise<ClaimData> {
  return fetchJSON<ClaimData>(`${BASE_URL}/api/claims/${encodeURIComponent(id)}`);
}

export async function getClaims(): Promise<ClaimData[]> {
  return fetchJSON<ClaimData[]>(`${BASE_URL}/api/claims`);
}

export async function submitApproval(
  data: ApprovalRequest
): Promise<DecisionReceipt> {
  return fetchJSON<DecisionReceipt>(`${BASE_URL}/api/approvals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function getReceipt(
  claimId: string
): Promise<DecisionReceipt> {
  return fetchJSON<DecisionReceipt>(
    `${BASE_URL}/api/claims/${encodeURIComponent(claimId)}/receipt`
  );
}

export async function getEvidence(
  claimId: string
): Promise<Evidence> {
  return fetchJSON<Evidence>(
    `${BASE_URL}/api/claims/${encodeURIComponent(claimId)}/evidence`
  );
}

export async function getAuditTrail(
  claimId: string
): Promise<AuditEntry[]> {
  return fetchJSON<AuditEntry[]>(
    `${BASE_URL}/api/claims/${encodeURIComponent(claimId)}/audit`
  );
}

export function createEventSource(claimId: string): EventSource {
  return new EventSource(
    `${BASE_URL}/api/claims/${encodeURIComponent(claimId)}/events`
  );
}

// ── Receipt verification ─────────────────────────────────────────────────────

export interface VerifyReceiptResult {
  valid: boolean;
  message: string;
  receipt_id?: string;
  verified_at?: string;
}

export interface VerificationKey {
  key_id: string;
  algorithm: string;
  public_key?: string;
  created_at?: string;
}

export async function verifyReceipt(
  receiptData: object
): Promise<VerifyReceiptResult> {
  return fetchJSON<VerifyReceiptResult>(`${BASE_URL}/api/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // Backend VerifyRequest expects { receipt: <obj> }, not the bare receipt.
    body: JSON.stringify({ receipt: receiptData }),
  });
}

export async function getVerificationKey(): Promise<VerificationKey> {
  return fetchJSON<VerificationKey>(`${BASE_URL}/api/verify/key`);
}

// ── Pending file (for voice/chat claim submissions) ─────────────────────────

export async function uploadPendingFile(
  file: File
): Promise<{ file_id: string; file_path: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${BASE_URL}/api/pending-file`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Failed to upload file");
  return res.json();
}

export async function clearPendingFile(): Promise<void> {
  await fetch(`${BASE_URL}/api/pending-file`, { method: "DELETE" });
}

// ── Chat streaming ──────────────────────────────────────────────────────────

export async function* streamChat(
  messages: Array<{ role: string; content: string }>,
  claimId?: string,
  signal?: AbortSignal
): AsyncGenerator<ChatEvent> {
  const response = await fetch(`${BASE_URL}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, claim_id: claimId }),
    signal,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "Unknown error");
    throw new Error(`Chat API Error ${response.status}: ${text}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data: ChatEvent = JSON.parse(line.slice(6));
          yield data;
        } catch {
          // skip unparseable SSE lines
        }
      }
    }
  }

  // Process any remaining buffer
  if (buffer.startsWith("data: ")) {
    try {
      const data: ChatEvent = JSON.parse(buffer.slice(6));
      yield data;
    } catch {
      // skip
    }
  }
}
