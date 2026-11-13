// A small typed client for the AuditIQ REST API.
import type { AiLayer, Analytics, ApplySummary, CaseAnswer, CaseGraphView, ConfigName, GraphAnswer, KnowledgeLayer, PeekMessage, RagTrace, StreamLogRow, StreamSources, SystemStatus, CopilotAnswer, DataAnswer, Health, Hit, InvoiceDetail, InvoiceRow, Job, LedgerLoad, Me, Overview, Pipeline, PolicyGraphData, PolicyOverview, Preview, Proposal, QueueItem, Results, Rings, Simulation, StreamStatus, VendorPoint } from "./types";

const TOKEN_KEY = "auditiq.token";

export class ApiError extends Error {
  readonly status: number;
  readonly problems: string[];

  constructor(status: number, message: string, problems: string[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.problems = problems;
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage may be unavailable (private window); the token then lasts for this page only
  }
}

/** The message of an error response: FastAPI puts it in `detail`, as text or as {message, problems}. */
function describe(status: number, body: unknown): ApiError {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return new ApiError(status, detail);
    if (Array.isArray(detail)) {
      const parts = detail.map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)));
      return new ApiError(status, parts.join("; "));
    }
    if (detail && typeof detail === "object") {
      const d = detail as { message?: string; problems?: string[] };
      return new ApiError(status, d.message ?? "request refused", d.problems ?? []);
    }
  }
  return new ApiError(status, `request failed (HTTP ${status})`);
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) throw describe(response.status, body);
  return body as T;
}

const json = (value: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(value) });

export const api = {
  health: () => request<Health>("/api/health"),
  me: () => request<Me>("/api/me"),
  overview: () => request<Overview>("/api/overview"),
  riskMap: () => request<{ vendors: VendorPoint[] }>("/api/risk-map"),
  analytics: () => request<Analytics>("/api/analytics"),
  rings: (limit = 40) => request<Rings>(`/api/rings?limit=${limit}`),
  pipeline: () => request<Pipeline>("/api/pipeline"),
  stream: () => request<StreamStatus>("/api/stream"),
  system: () => request<SystemStatus>("/api/system"),
  streamSources: () => request<StreamSources>("/api/stream/sources"),
  streamPublish: (body: { source: "ledger" | "mailbox" | "policy"; name: string; limit?: number; activate?: boolean }) =>
    request<Job<{ source: string; name: string; sent: Record<string, number> }>>("/api/stream/publish", json(body)),
  streamWork: (body: { kinds?: string[]; idle_exit?: number }) =>
    request<Job<{ counts: Record<string, Record<string, number>> }>>("/api/stream/work", json(body)),
  streamLog: (limit = 60) => request<{ messages: StreamLogRow[] }>(`/api/stream/log?limit=${limit}`),
  streamPeek: (kind: string, n = 8) => request<{ topic: string; messages: PeekMessage[] }>(`/api/stream/peek?kind=${kind}&n=${n}`),
  ragTrace: (q: string, k = 5) => request<RagTrace>(`/api/rag/trace?q=${encodeURIComponent(q)}&k=${k}`),
  knowledge: () => request<KnowledgeLayer>("/api/knowledge"),
  ai: () => request<AiLayer>("/api/ai"),
  queue: (limit = 500, level?: string) =>
    request<{ total: number; items: QueueItem[]; rules: Record<string, string | null>; levels?: Partial<Record<string, { invoices: number; amount: number }>> }>(
      `/api/queue?limit=${limit}${level ? `&level=${level}` : ""}`,
    ),
  invoices: (q: string, limit = 50) =>
    request<{ items: InvoiceRow[] }>(`/api/invoices?q=${encodeURIComponent(q)}&limit=${limit}`),
  invoice: (id: string, withLabel = false) =>
    request<InvoiceDetail>(`/api/invoices/${encodeURIComponent(id)}${withLabel ? "?with_label=true" : ""}`),
  decide: (resultId: number, decision: "approve" | "reject" | "override", reviewer: string, justification: string) =>
    request<{ result_id: number; invoice_id: string; workflow_status: string }>(
      `/api/results/${resultId}/decision`,
      json({ decision, reviewer, justification }),
    ),
  audit: (id: string, config: ConfigName) =>
    request<Job<{ run_id: number; invoice_id: string; route: string; workflow_status: string }>>(
      `/api/invoices/${encodeURIComponent(id)}/audit`,
      json({ config }),
    ),
  loadLedger: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    form.append("replace", "true");
    return request<Job<LedgerLoad>>("/api/ledger", { method: "POST", body: form });
  },
  policy: () => request<PolicyOverview>("/api/policy"),
  policyGraph: (version?: string) =>
    request<PolicyGraphData>(`/api/policy/graph${version ? `?version=${encodeURIComponent(version)}` : ""}`),
  askGraph: (q: string, version?: string) =>
    request<GraphAnswer>(`/api/policy/graph/ask?q=${encodeURIComponent(q)}${version ? `&version=${encodeURIComponent(version)}` : ""}`),
  caseGraph: (focus?: string) =>
    request<CaseGraphView>(`/api/case-graph${focus ? `?focus=${encodeURIComponent(focus)}` : ""}`),
  askCaseGraph: (q: string) => request<CaseAnswer>(`/api/case-graph/ask?q=${encodeURIComponent(q)}`),
  activate: (version: string) => request<{ active: string }>("/api/policy/activate", json({ version })),
  preview: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Preview>("/api/policy/preview", { method: "POST", body: form });
  },
  adopt: (uploadId: string, activate: boolean, replace: boolean) =>
    request<{ version: string; adopted: boolean; active?: boolean }>(
      "/api/policy/adopt",
      json({ upload_id: uploadId, activate, replace }),
    ),
  propose: (uploadId: string) => request<Job<Proposal>>("/api/policy/propose", json({ upload_id: uploadId })),
  simulate: (uploadId: string) => request<Job<Simulation>>("/api/policy/simulate", json({ upload_id: uploadId })),
  confirm: (body: {
    upload_id: string;
    reviewer: string;
    accept_verified: boolean;
    values: Record<string, unknown>;
    passages: Record<string, string>;
    version?: string | null;
    activate: boolean;
  }) => request<{ version: string; adopted: boolean }>("/api/policy/confirm", json(body)),
  applyPolicy: () => request<Job<ApplySummary>>("/api/policy/apply", { method: "POST" }),
  search: (q: string, k = 4) =>
    request<{ mode: string; restated: string | null; hits: Hit[] }>(`/api/search?q=${encodeURIComponent(q)}&k=${k}`),
  ask: (question: string, invoiceId?: string) =>
    request<Job<CopilotAnswer>>("/api/copilot/ask", json({ question, invoice_id: invoiceId || null })),
  askData: (question: string) => request<Job<DataAnswer>>("/api/copilot/data", json({ question })),
  job: <T>(id: string) => request<Job<T>>(`/api/jobs/${id}`),
  results: () => request<Results>("/api/results"),
};

/** Poll a background job until it is done or has failed. */
export async function waitForJob<T>(
  job: Job<T>,
  onProgress?: (job: Job<T>) => void,
  intervalMs = 1000,
  signal?: AbortSignal,
): Promise<T> {
  let current = job;
  for (;;) {
    onProgress?.(current);
    if (current.status === "done") return current.result as T;
    if (current.status === "failed") throw new ApiError(500, current.error ?? "the job failed");
    if (signal?.aborted) throw new ApiError(499, "cancelled");
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    current = await api.job<T>(current.id);
  }
}
