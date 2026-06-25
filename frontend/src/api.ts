import type {
  AgentRunRequest,
  AgentRunResponse,
  ChatMessage,
  ConfigTestResponse,
  DocumentIndexTaskState,
  DocumentSearchResponse,
  HealthResponse,
  JobApplicationReviewResponse,
  MCPCapabilitiesResponse,
  RuntimeConfigUpdate,
  RuntimeConfigView,
  TraceRecord
} from "./types";

export const DEFAULT_API_BASE =
  import.meta.env.VITE_API_BASE_URL?.trim() || "http://127.0.0.1:8025/api/v1";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function normalizeApiBase(apiBase: string): string {
  const trimmed = apiBase.trim().replace(/\/+$/, "");
  if (!trimmed) {
    throw new ApiError(0, "API Base URL 不能为空。");
  }
  return trimmed;
}

function endpoint(apiBase: string, path: string): string {
  return `${normalizeApiBase(apiBase)}${path}`;
}

async function readError(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
    return JSON.stringify(body.detail ?? body);
  }
  const text = await response.text();
  return text || `HTTP ${response.status}`;
}

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new ApiError(response.status, await readError(response));
  }
  return (await response.json()) as T;
}

export async function checkHealth(apiBase: string): Promise<HealthResponse> {
  return requestJson<HealthResponse>(endpoint(apiBase, "/health"));
}

export async function getConfig(apiBase: string): Promise<RuntimeConfigView> {
  return requestJson<RuntimeConfigView>(endpoint(apiBase, "/config"));
}

export async function updateConfig(
  apiBase: string,
  update: RuntimeConfigUpdate
): Promise<RuntimeConfigView> {
  return requestJson<RuntimeConfigView>(endpoint(apiBase, "/config"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update)
  });
}

export async function testConfig(apiBase: string): Promise<ConfigTestResponse> {
  return requestJson<ConfigTestResponse>(endpoint(apiBase, "/config/test"), {
    method: "POST"
  });
}

export async function uploadDocumentAsync(
  apiBase: string,
  file: File
): Promise<DocumentIndexTaskState> {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<DocumentIndexTaskState>(endpoint(apiBase, "/documents/upload/async"), {
    method: "POST",
    body: formData
  });
}

export async function getDocumentTask(
  apiBase: string,
  taskId: string
): Promise<DocumentIndexTaskState> {
  return requestJson<DocumentIndexTaskState>(
    endpoint(apiBase, `/documents/tasks/${encodeURIComponent(taskId)}`)
  );
}

export async function searchDocuments(
  apiBase: string,
  query: string,
  topK: number
): Promise<DocumentSearchResponse> {
  return requestJson<DocumentSearchResponse>(endpoint(apiBase, "/documents/search"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK })
  });
}

export async function runAgent(
  apiBase: string,
  request: AgentRunRequest
): Promise<AgentRunResponse> {
  return requestJson<AgentRunResponse>(endpoint(apiBase, "/agent/run"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request)
  });
}

export type ParsedSSEEvent = { id: string | null; data: string };

// 纯函数 SSE 解析器：按 \n\n 切分事件，解析 id 和 data 行，返回事件和未消费的剩余 buffer。
export function parseSSEBuffer(buffer: string): {
  events: ParsedSSEEvent[];
  rest: string;
} {
  const events: ParsedSSEEvent[] = [];
  let rest = buffer;
  let separatorIndex = rest.indexOf("\n\n");
  while (separatorIndex !== -1) {
    const rawEvent = rest.slice(0, separatorIndex);
    rest = rest.slice(separatorIndex + 2);
    let id: string | null = null;
    const dataLines: string[] = [];
    for (const line of rawEvent.split("\n")) {
      if (line.startsWith("id:")) {
        id = line.slice(3).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }
    if (dataLines.length > 0) {
      events.push({ id, data: dataLines.join("\n") });
    }
    separatorIndex = rest.indexOf("\n\n");
  }
  return { events, rest };
}

export type StreamChatCallbacks = {
  onReasoning?: (text: string, id: string | null) => void;
  onContent?: (text: string, id: string | null) => void;
  onDone?: (finishReason: string | null) => void;
  onError?: (status: number, message: string) => void;
};

export type StreamChatOptions = StreamChatCallbacks & {
  model?: string;
  maxTokens?: number;
  signal?: AbortSignal;
  lastEventId?: string;
};

type StreamChatPayload = {
  delta?: string;
  type?: string;
  done?: boolean;
  finish_reason?: string | null;
  error?: { status_code: number; message: string };
};

export async function streamChat(
  apiBase: string,
  messages: ChatMessage[],
  options: StreamChatOptions = {}
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.lastEventId) {
    headers["Last-Event-ID"] = options.lastEventId;
  }

  const response = await fetch(endpoint(apiBase, "/chat/stream"), {
    method: "POST",
    headers,
    body: JSON.stringify({
      messages,
      model: options.model,
      max_tokens: options.maxTokens ?? 2000
    }),
    signal: options.signal
  });

  if (!response.ok || !response.body) {
    throw new ApiError(response.status, await readError(response));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseSSEBuffer(buffer);
    buffer = rest;
    for (const event of events) {
      let payload: StreamChatPayload;
      try {
        payload = JSON.parse(event.data) as StreamChatPayload;
      } catch {
        continue;
      }
      if (payload.error) {
        options.onError?.(payload.error.status_code, payload.error.message);
        return;
      }
      if (payload.done) {
        options.onDone?.(payload.finish_reason ?? null);
        return;
      }
      if (payload.type === "reasoning" && payload.delta) {
        options.onReasoning?.(payload.delta, event.id);
      } else if (payload.type === "content" && payload.delta) {
        options.onContent?.(payload.delta, event.id);
      }
    }
  }
}

export async function startJobApplicationReview(
  apiBase: string,
  jdText: string,
  topK: number
): Promise<JobApplicationReviewResponse> {
  return requestJson<JobApplicationReviewResponse>(
    endpoint(apiBase, "/agent/job-application/review"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jd_text: jdText, top_k: topK })
    }
  );
}

export async function resumeJobApplicationReview(
  apiBase: string,
  threadId: string,
  note: string,
  approved: boolean
): Promise<JobApplicationReviewResponse> {
  return requestJson<JobApplicationReviewResponse>(
    endpoint(apiBase, "/agent/job-application/resume"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId, note, approved })
    }
  );
}

export async function getMcpCapabilities(
  apiBase: string
): Promise<MCPCapabilitiesResponse> {
  return requestJson<MCPCapabilitiesResponse>(endpoint(apiBase, "/mcp/capabilities"));
}

export async function getTraces(
  apiBase: string,
  limit = 20
): Promise<TraceRecord[]> {
  return requestJson<TraceRecord[]>(endpoint(apiBase, `/traces?limit=${limit}`));
}
