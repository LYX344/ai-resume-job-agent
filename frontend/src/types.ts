export type HealthResponse = {
  status: string;
  app_name: string;
  app_env: string;
  app_version: string;
};

export type DocumentIndexTaskStatus = "pending" | "running" | "done" | "failed";

export type DocumentIndexTaskState = {
  task_id: string;
  status: DocumentIndexTaskStatus;
  file_name: string;
  file_type: string | null;
  document_id: string | null;
  chunk_count: number;
  indexed_keys: string[];
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type DocumentSearchResult = {
  key: string;
  content: string;
  metadata: Record<string, unknown>;
  distance: number;
};

export type DocumentSearchResponse = {
  query: string;
  top_k: number;
  results: DocumentSearchResult[];
};

export type RagSource = {
  source_id: number;
  key: string;
  content: string;
  metadata: Record<string, unknown>;
  distance: number;
};

export type AgentStep = {
  name: string;
  status: "completed" | "skipped";
  detail: string;
  data: Record<string, unknown>;
};

export type AgentRunResponse = {
  answer: string;
  intent: string;
  session_id: string | null;
  memory_used: boolean;
  used_knowledge_base: boolean;
  sources: RagSource[];
  steps: AgentStep[];
  model: string | null;
  finish_reason: string | null;
  usage: Record<string, unknown> | null;
};

export type AgentRunRequest = {
  query: string;
  session_id?: string;
  use_knowledge_base: boolean;
  top_k: number;
};

export type ChatMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type ChatStreamDeltaType = "reasoning" | "content";

export type JobApplicationStepInfo = {
  agent: string;
  status: string;
  detail: string;
};

export type JobApplicationReviewResponse = {
  status: string;
  thread_id: string;
  resume_summary: string;
  match_analysis: string;
  application_material: string;
  review_payload: Record<string, unknown> | null;
  steps: JobApplicationStepInfo[];
};

export type MCPToolInfo = {
  server: string;
  name: string;
  qualified_name: string;
  description: string;
  input_schema: Record<string, unknown>;
};

export type MCPResourceInfo = {
  server: string;
  name: string;
  uri: string;
  description: string;
  mime_type: string;
};

export type MCPPromptInfo = {
  server: string;
  name: string;
  description: string;
  arguments: Record<string, unknown>[];
};

export type MCPServerStatus = {
  name: string;
  transport: string;
  connected: boolean;
  tool_count: number;
  resource_count: number;
  prompt_count: number;
  error: string | null;
};

export type MCPCapabilitiesResponse = {
  enabled: boolean;
  config_path: string;
  server_count: number;
  servers: MCPServerStatus[];
  tools: MCPToolInfo[];
  resources: MCPResourceInfo[];
  prompts: MCPPromptInfo[];
};

export type TraceStep = {
  name: string;
  status: string;
  detail: string;
};

export type TraceToolCall = {
  name: string;
  status: string;
  kind: string;
};

export type TraceRecord = {
  trace_id: string;
  kind: string;
  query: string;
  intent: string;
  started_at: string;
  duration_ms: number;
  step_count: number;
  steps: TraceStep[];
  usage: Record<string, unknown> | null;
  model: string | null;
  tool_calls: TraceToolCall[];
};

export type ModelConfigView = {
  provider: string;
  base_url: string;
  model: string;
  api_key_set: boolean;
  api_key_masked: string;
  dimensions: number | null;
};

export type RuntimeConfigView = {
  llm: ModelConfigView;
  embedding: ModelConfigView;
  rerank: ModelConfigView;
};

export type ModelConfigUpdate = {
  provider?: string;
  base_url?: string;
  model?: string;
  api_key?: string;
  dimensions?: number;
};

export type RuntimeConfigUpdate = {
  llm?: ModelConfigUpdate;
  embedding?: ModelConfigUpdate;
  rerank?: ModelConfigUpdate;
};

export type ServiceTestResult = {
  ok: boolean;
  message: string;
};

export type ConfigTestResponse = {
  embedding: ServiceTestResult;
  llm: ServiceTestResult;
  rerank: ServiceTestResult;
};
