import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Database,
  FileSearch,
  Loader2,
  Plug,
  Search,
  Send,
  Server,
  SlidersHorizontal,
  UploadCloud,
  XCircle
} from "lucide-react";
import {
  ApiError,
  DEFAULT_API_BASE,
  checkHealth,
  getConfig,
  getDocumentTask,
  getMcpCapabilities,
  getTraces,
  resumeJobApplicationReview,
  runAgent,
  searchDocuments,
  startJobApplicationReview,
  streamChat,
  testConfig,
  updateConfig,
  uploadDocumentAsync
} from "./api";
import type {
  AgentRunResponse,
  ChatMessage,
  ConfigTestResponse,
  DocumentIndexTaskState,
  DocumentSearchResult,
  HealthResponse,
  JobApplicationReviewResponse,
  MCPCapabilitiesResponse,
  ModelConfigUpdate,
  ModelConfigView,
  RagSource,
  RuntimeConfigUpdate,
  RuntimeConfigView,
  TraceRecord
} from "./types";

type LoadState = "idle" | "loading" | "success" | "error";

function toErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.status > 0 ? `${error.status}: ${error.message}` : error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "未知错误。";
}

function clampTopK(value: number): number {
  return Math.min(20, Math.max(1, value));
}

function metadataText(
  metadata: Record<string, unknown>,
  keys: string[],
  fallback = "unknown"
): string {
  for (const key of keys) {
    const value = metadata[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
    if (typeof value === "number") {
      return String(value);
    }
  }
  return fallback;
}

function formatDistance(distance: number): string {
  return Number.isFinite(distance) ? distance.toFixed(4) : "-";
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge status-${status}`}>{status}</span>;
}

function LoadingIcon({ active }: { active: boolean }) {
  return active ? <Loader2 aria-hidden="true" className="spin" size={16} /> : null;
}

function SourceList({ sources }: { sources: RagSource[] }) {
  if (sources.length === 0) {
    return <p className="empty-text">没有引用来源。</p>;
  }

  return (
    <div className="result-list">
      {sources.map((source) => (
        <article className="result-row" key={`${source.source_id}-${source.key}`}>
          <div className="result-row-head">
            <strong>[{source.source_id}] {metadataText(source.metadata, ["source", "file_name"])}</strong>
            <span>distance {formatDistance(source.distance)}</span>
          </div>
          <p>{source.content}</p>
        </article>
      ))}
    </div>
  );
}

function SearchResults({ results }: { results: DocumentSearchResult[] }) {
  if (results.length === 0) {
    return <p className="empty-text">暂无检索结果。</p>;
  }

  return (
    <div className="result-list">
      {results.map((result) => (
        <article className="result-row" key={result.key}>
          <div className="result-row-head">
            <strong>{metadataText(result.metadata, ["source", "file_name"])}</strong>
            <span>distance {formatDistance(result.distance)}</span>
          </div>
          <p>{result.content}</p>
          <code>{result.key}</code>
        </article>
      ))}
    </div>
  );
}

function AgentSteps({ response }: { response: AgentRunResponse | null }) {
  if (!response) {
    return <p className="empty-text">Agent 运行后会显示步骤。</p>;
  }

  return (
    <ol className="step-list">
      {response.steps.map((step, index) => (
        <li key={`${step.name}-${index}`}>
          <div>
            <strong>{step.name}</strong>
            <span>{step.detail}</span>
          </div>
          <StatusBadge status={step.status} />
        </li>
      ))}
    </ol>
  );
}

function McpCapabilities({ data }: { data: MCPCapabilitiesResponse }) {
  if (!data.enabled) {
    return (
      <p className="empty-text">
        MCP 未启用。设置 MCP_ENABLED=true 并配置 data/mcp/servers.json 后可发现外部工具。
      </p>
    );
  }
  if (data.servers.length === 0) {
    return <p className="empty-text">没有配置 MCP server。</p>;
  }

  return (
    <div className="result-list">
      {data.servers.map((server) => (
        <article className="result-row" key={`server-${server.name}`}>
          <div className="result-row-head">
            <strong>{server.name}（{server.transport}）</strong>
            <StatusBadge status={server.connected ? "connected" : "error"} />
          </div>
          <p>
            tools {server.tool_count} · resources {server.resource_count} · prompts{" "}
            {server.prompt_count}
            {server.error ? ` · ${server.error}` : ""}
          </p>
        </article>
      ))}
      {data.tools.map((tool) => (
        <article className="result-row" key={`tool-${tool.qualified_name}`}>
          <div className="result-row-head">
            <strong>{tool.qualified_name}</strong>
            <span>tool</span>
          </div>
          <p>{tool.description}</p>
        </article>
      ))}
      {data.resources.map((resource) => (
        <article className="result-row" key={`resource-${resource.uri}`}>
          <div className="result-row-head">
            <strong>{resource.name || resource.uri}</strong>
            <span>resource</span>
          </div>
          {resource.description && <p>{resource.description}</p>}
          <code>{resource.uri}</code>
        </article>
      ))}
      {data.prompts.map((prompt) => (
        <article className="result-row" key={`prompt-${prompt.name}`}>
          <div className="result-row-head">
            <strong>{prompt.name}</strong>
            <span>prompt</span>
          </div>
          {prompt.description && <p>{prompt.description}</p>}
        </article>
      ))}
    </div>
  );
}

function TraceList({ traces }: { traces: TraceRecord[] }) {
  if (traces.length === 0) {
    return <p className="empty-text">暂无运行记录。运行 Agent 后会生成 trace。</p>;
  }

  return (
    <div className="result-list">
      {traces.map((trace) => (
        <article className="result-row" key={trace.trace_id}>
          <div className="result-row-head">
            <strong>{trace.intent || trace.kind}</strong>
            <span>{trace.duration_ms.toFixed(0)} ms</span>
          </div>
          {trace.query && <p>{trace.query}</p>}
          {trace.tool_calls.length > 0 && (
            <p className="trace-tools">
              {trace.tool_calls.map((call, index) => (
                <span
                  className={`status-badge status-${call.kind}`}
                  key={`${trace.trace_id}-tc-${index}`}
                >
                  {call.name}（{call.kind}）
                </span>
              ))}
            </p>
          )}
          <code>
            {trace.model || "-"} · steps {trace.step_count}
          </code>
        </article>
      ))}
    </div>
  );
}

type ModelFormState = {
  provider: string;
  base_url: string;
  model: string;
  api_key: string;
  dimensions: string;
};

const EMPTY_MODEL_FORM: ModelFormState = {
  provider: "",
  base_url: "",
  model: "",
  api_key: "",
  dimensions: ""
};

function viewToForm(view: ModelConfigView): ModelFormState {
  return {
    provider: view.provider,
    base_url: view.base_url,
    model: view.model,
    api_key: "",
    dimensions: view.dimensions != null ? String(view.dimensions) : ""
  };
}

function formToUpdate(form: ModelFormState, includeDimensions: boolean): ModelConfigUpdate {
  const update: ModelConfigUpdate = {};
  if (form.provider.trim()) update.provider = form.provider.trim();
  if (form.base_url.trim()) update.base_url = form.base_url.trim();
  if (form.model.trim()) update.model = form.model.trim();
  if (form.api_key.trim()) update.api_key = form.api_key.trim();
  if (includeDimensions && form.dimensions.trim()) {
    const parsed = Number(form.dimensions);
    if (Number.isFinite(parsed) && parsed > 0) {
      update.dimensions = parsed;
    }
  }
  return update;
}

function ModelFields({
  title,
  subtitle,
  form,
  masked,
  onChange,
  showDimensions = false
}: {
  title: string;
  subtitle: string;
  form: ModelFormState;
  masked: string;
  onChange: (next: ModelFormState) => void;
  showDimensions?: boolean;
}) {
  return (
    <fieldset className="config-group">
      <legend>
        {title} <span className="muted">{subtitle}</span>
      </legend>
      <div className="field">
        <label>Provider</label>
        <input
          value={form.provider}
          onChange={(event) => onChange({ ...form, provider: event.target.value })}
          spellCheck={false}
        />
      </div>
      <div className="field">
        <label>Base URL</label>
        <input
          value={form.base_url}
          onChange={(event) => onChange({ ...form, base_url: event.target.value })}
          spellCheck={false}
        />
      </div>
      <div className="field">
        <label>Model</label>
        <input
          value={form.model}
          onChange={(event) => onChange({ ...form, model: event.target.value })}
          spellCheck={false}
        />
      </div>
      <div className="field">
        <label>API Key</label>
        <input
          type="password"
          value={form.api_key}
          placeholder={masked || "未设置（留空表示不修改）"}
          onChange={(event) => onChange({ ...form, api_key: event.target.value })}
          spellCheck={false}
        />
      </div>
      {showDimensions && (
        <div className="field">
          <label>Dimensions</label>
          <input
            type="number"
            value={form.dimensions}
            onChange={(event) => onChange({ ...form, dimensions: event.target.value })}
          />
        </div>
      )}
    </fieldset>
  );
}

function ModelConfigPanel({ apiBase }: { apiBase: string }) {
  const [view, setView] = useState<RuntimeConfigView | null>(null);
  const [llm, setLlm] = useState<ModelFormState>(EMPTY_MODEL_FORM);
  const [embedding, setEmbedding] = useState<ModelFormState>(EMPTY_MODEL_FORM);
  const [rerank, setRerank] = useState<ModelFormState>(EMPTY_MODEL_FORM);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [saveState, setSaveState] = useState<LoadState>("idle");
  const [testState, setTestState] = useState<LoadState>("idle");
  const [testResult, setTestResult] = useState<ConfigTestResponse | null>(null);
  const [error, setError] = useState("");

  function applyView(next: RuntimeConfigView) {
    setView(next);
    setLlm(viewToForm(next.llm));
    setEmbedding(viewToForm(next.embedding));
    setRerank(viewToForm(next.rerank));
  }

  async function load() {
    setLoadState("loading");
    setError("");
    try {
      const result = await getConfig(apiBase);
      applyView(result);
      setLoadState("success");
    } catch (err) {
      setError(toErrorMessage(err));
      setLoadState("error");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  async function handleSave() {
    setSaveState("loading");
    setError("");
    const update: RuntimeConfigUpdate = {
      llm: formToUpdate(llm, false),
      embedding: formToUpdate(embedding, true),
      rerank: formToUpdate(rerank, false)
    };
    try {
      const result = await updateConfig(apiBase, update);
      applyView(result);
      setTestResult(null);
      setSaveState("success");
    } catch (err) {
      setError(toErrorMessage(err));
      setSaveState("error");
    }
  }

  async function handleTest() {
    setTestState("loading");
    setError("");
    try {
      const result = await testConfig(apiBase);
      setTestResult(result);
      setTestState("success");
    } catch (err) {
      setError(toErrorMessage(err));
      setTestState("error");
    }
  }

  return (
    <article className="panel">
      <div className="panel-header">
        <SlidersHorizontal aria-hidden="true" size={20} />
        <div>
          <h2>模型配置</h2>
          <span>LLM / 向量化 / Rerank</span>
        </div>
      </div>
      <p className="hint-text">
        填写各模型的 base_url / model / api_key，保存后立即生效（无需重启）。API Key 留空表示沿用现有值。
      </p>
      <div className="stack">
        <ModelFields
          title="大模型 LLM"
          subtitle="Chat / Agent"
          form={llm}
          masked={view?.llm.api_key_masked ?? ""}
          onChange={setLlm}
        />
        <ModelFields
          title="向量化 Embedding"
          subtitle="文档向量化"
          form={embedding}
          masked={view?.embedding.api_key_masked ?? ""}
          onChange={setEmbedding}
          showDimensions
        />
        <ModelFields
          title="重排 Rerank"
          subtitle="两阶段检索精排"
          form={rerank}
          masked={view?.rerank.api_key_masked ?? ""}
          onChange={setRerank}
        />
      </div>
      <div className="inline-fields">
        <button
          className="button primary"
          type="button"
          onClick={handleSave}
          disabled={saveState === "loading"}
        >
          保存配置
          <LoadingIcon active={saveState === "loading"} />
        </button>
        <button
          className="button secondary"
          type="button"
          onClick={handleTest}
          disabled={testState === "loading"}
        >
          测试连通
          <LoadingIcon active={testState === "loading"} />
        </button>
        <button
          className="button secondary"
          type="button"
          onClick={() => void load()}
          disabled={loadState === "loading"}
        >
          重新加载
          <LoadingIcon active={loadState === "loading"} />
        </button>
      </div>
      {saveState === "success" && <p className="success-text">配置已保存并生效。</p>}
      {testResult && (
        <div className="task-box">
          {(["llm", "embedding", "rerank"] as const).map((key) => (
            <div className="task-line" key={key}>
              <span>{key}</span>
              <span className={testResult[key].ok ? "success-text" : "error-text"}>
                {testResult[key].ok ? "OK" : "失败"}：{testResult[key].message}
              </span>
            </div>
          ))}
        </div>
      )}
      {error && <p className="error-text">{error}</p>}
    </article>
  );
}

export default function App() {
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [healthState, setHealthState] = useState<LoadState>("idle");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState("");

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadState, setUploadState] = useState<LoadState>("idle");
  const [taskState, setTaskState] = useState<DocumentIndexTaskState | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [pollError, setPollError] = useState("");

  const [searchQuery, setSearchQuery] = useState("Redis RAG Agent");
  const [searchTopK, setSearchTopK] = useState(3);
  const [searchState, setSearchState] = useState<LoadState>("idle");
  const [searchResults, setSearchResults] = useState<DocumentSearchResult[]>([]);
  const [searchError, setSearchError] = useState("");

  const [sessionId, setSessionId] = useState("demo-frontend");
  const [useKnowledgeBase, setUseKnowledgeBase] = useState(false);
  const [agentTopK, setAgentTopK] = useState(3);
  const [agentQuery, setAgentQuery] = useState("请计算 2 + 3 * 4 等于多少？");
  const [agentState, setAgentState] = useState<LoadState>("idle");
  const [agentResponse, setAgentResponse] = useState<AgentRunResponse | null>(null);
  const [agentError, setAgentError] = useState("");

  const [memoryText, setMemoryText] = useState("请记住：我喜欢先给结论");
  const [memoryState, setMemoryState] = useState<LoadState>("idle");
  const [memoryError, setMemoryError] = useState("");

  const [streamInput, setStreamInput] = useState("用三句话介绍 Redis 在后端项目里的作用");
  const [streamReasoning, setStreamReasoning] = useState("");
  const [streamContent, setStreamContent] = useState("");
  const [streamState, setStreamState] = useState<LoadState>("idle");
  const [streamFinishReason, setStreamFinishReason] = useState<string | null>(null);
  const [streamError, setStreamError] = useState("");

  const [jobJd, setJobJd] = useState(
    "招聘 AI 应用开发实习生：要求熟悉 Python、LangChain/LangGraph、RAG 与向量检索，了解 FastAPI 和 Redis。"
  );
  const [jobNote, setJobNote] = useState("");
  const [jobState, setJobState] = useState<LoadState>("idle");
  const [jobResult, setJobResult] = useState<JobApplicationReviewResponse | null>(null);
  const [jobError, setJobError] = useState("");

  const [mcpState, setMcpState] = useState<LoadState>("idle");
  const [mcp, setMcp] = useState<MCPCapabilitiesResponse | null>(null);
  const [mcpError, setMcpError] = useState("");

  const [traceState, setTraceState] = useState<LoadState>("idle");
  const [traces, setTraces] = useState<TraceRecord[]>([]);
  const [traceError, setTraceError] = useState("");
  const streamAbortRef = useRef<AbortController | null>(null);

  const activeTask = taskState?.status === "pending" || taskState?.status === "running";
  const healthLabel = useMemo(() => {
    if (healthState === "success" && health) {
      return `${health.app_name} ${health.app_version}`;
    }
    if (healthState === "error") {
      return "连接失败";
    }
    if (healthState === "loading") {
      return "检查中";
    }
    return "未检查";
  }, [health, healthState]);

  useEffect(() => {
    void handleHealthCheck();
  }, []);

  useEffect(() => {
    if (!taskState || !activeTask) {
      return;
    }

    const timer = window.setInterval(() => {
      getDocumentTask(apiBase, taskState.task_id)
        .then((nextTask) => {
          setTaskState(nextTask);
          setPollError("");
        })
        .catch((error: unknown) => setPollError(toErrorMessage(error)));
    }, 1200);

    return () => window.clearInterval(timer);
  }, [activeTask, apiBase, taskState]);

  async function handleLoadMcp() {
    setMcpState("loading");
    setMcpError("");
    try {
      const result = await getMcpCapabilities(apiBase);
      setMcp(result);
      setMcpState("success");
    } catch (error) {
      setMcpError(toErrorMessage(error));
      setMcpState("error");
    }
  }

  async function handleLoadTraces() {
    setTraceState("loading");
    setTraceError("");
    try {
      const result = await getTraces(apiBase);
      setTraces(result);
      setTraceState("success");
    } catch (error) {
      setTraceError(toErrorMessage(error));
      setTraceState("error");
    }
  }

  async function handleHealthCheck() {
    setHealthState("loading");
    setHealthError("");
    try {
      const result = await checkHealth(apiBase);
      setHealth(result);
      setHealthState("success");
    } catch (error) {
      setHealth(null);
      setHealthError(toErrorMessage(error));
      setHealthState("error");
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) {
      setUploadError("请选择一个 .md、.txt、.docx 或 .pdf 文件。");
      setUploadState("error");
      return;
    }

    setUploadState("loading");
    setUploadError("");
    setPollError("");
    try {
      const result = await uploadDocumentAsync(apiBase, selectedFile);
      setTaskState(result);
      setUploadState("success");
    } catch (error) {
      setTaskState(null);
      setUploadError(toErrorMessage(error));
      setUploadState("error");
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearchState("loading");
    setSearchError("");
    try {
      const result = await searchDocuments(apiBase, searchQuery.trim(), clampTopK(searchTopK));
      setSearchResults(result.results);
      setSearchState("success");
    } catch (error) {
      setSearchResults([]);
      setSearchError(toErrorMessage(error));
      setSearchState("error");
    }
  }

  async function handleAgentRun(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    setAgentState("loading");
    setAgentError("");
    try {
      const result = await runAgent(apiBase, {
        query: agentQuery.trim(),
        session_id: sessionId.trim() || undefined,
        use_knowledge_base: useKnowledgeBase,
        top_k: clampTopK(agentTopK)
      });
      setAgentResponse(result);
      setAgentState("success");
    } catch (error) {
      setAgentResponse(null);
      setAgentError(toErrorMessage(error));
      setAgentState("error");
    }
  }

  async function handleMemoryUpdate() {
    if (!sessionId.trim()) {
      setMemoryError("记忆写入需要 session_id。");
      setMemoryState("error");
      return;
    }

    setMemoryState("loading");
    setMemoryError("");
    try {
      const result = await runAgent(apiBase, {
        query: memoryText.trim(),
        session_id: sessionId.trim(),
        use_knowledge_base: false,
        top_k: clampTopK(agentTopK)
      });
      setAgentResponse(result);
      setAgentState("success");
      setMemoryState("success");
    } catch (error) {
      setMemoryError(toErrorMessage(error));
      setMemoryState("error");
    }
  }

  async function handleStartJobReview(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    setJobState("loading");
    setJobError("");
    setJobResult(null);
    try {
      const result = await startJobApplicationReview(apiBase, jobJd, 5);
      setJobResult(result);
      setJobState("success");
    } catch (error) {
      setJobError(toErrorMessage(error));
      setJobState("error");
    }
  }

  async function handleResumeJobReview() {
    if (!jobResult) {
      return;
    }
    setJobState("loading");
    setJobError("");
    try {
      const result = await resumeJobApplicationReview(
        apiBase,
        jobResult.thread_id,
        jobNote,
        true
      );
      setJobResult(result);
      setJobState("success");
    } catch (error) {
      setJobError(toErrorMessage(error));
      setJobState("error");
    }
  }

  async function handleStreamChat(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const text = streamInput.trim();
    if (!text) {
      setStreamError("请输入要发送的内容。");
      setStreamState("error");
      return;
    }

    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;

    setStreamReasoning("");
    setStreamContent("");
    setStreamFinishReason(null);
    setStreamError("");
    setStreamState("loading");

    const messages: ChatMessage[] = [{ role: "user", content: text }];
    try {
      await streamChat(apiBase, messages, {
        signal: controller.signal,
        onReasoning: (delta) => setStreamReasoning((prev) => prev + delta),
        onContent: (delta) => setStreamContent((prev) => prev + delta),
        onDone: (finishReason) => {
          setStreamFinishReason(finishReason);
          setStreamState("success");
        },
        onError: (status, message) => {
          setStreamError(`${status}: ${message}`);
          setStreamState("error");
        }
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setStreamState("idle");
        return;
      }
      setStreamError(toErrorMessage(error));
      setStreamState("error");
    }
  }

  function handleStopStream() {
    streamAbortRef.current?.abort();
    setStreamState("idle");
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        跳到主内容
      </a>
      <header className="topbar">
        <div>
          <p className="eyebrow">AI Resume Job Agent</p>
          <h1>Agent 控制台</h1>
        </div>
        <div className="topbar-status" aria-live="polite">
          <span className={`status-dot ${healthState}`} />
          <span>{healthLabel}</span>
        </div>
      </header>

      <main className="layout" id="main">
        <section className="left-column" aria-label="数据与检索">
          <article className="panel">
            <div className="panel-header">
              <Server aria-hidden="true" size={20} />
              <div>
                <h2>后端连接</h2>
                <span>FastAPI</span>
              </div>
            </div>
            <div className="field">
              <label htmlFor="api-base">API Base URL</label>
              <input
                id="api-base"
                value={apiBase}
                onChange={(event) => setApiBase(event.target.value)}
                spellCheck={false}
              />
            </div>
            <button className="button secondary" type="button" onClick={handleHealthCheck}>
              <Activity aria-hidden="true" size={16} />
              检查连接
              <LoadingIcon active={healthState === "loading"} />
            </button>
            {healthError && <p className="error-text">{healthError}</p>}
          </article>

          <ModelConfigPanel apiBase={apiBase} />

          <article className="panel">
            <div className="panel-header">
              <UploadCloud aria-hidden="true" size={20} />
              <div>
                <h2>文档入库</h2>
                <span>Async Indexing</span>
              </div>
            </div>
            <form className="stack" onSubmit={handleUpload}>
              <div className="field">
                <label htmlFor="doc-file">文件</label>
                <input
                  id="doc-file"
                  type="file"
                  accept=".md,.txt,.docx,.pdf,text/markdown,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf"
                  onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                />
              </div>
              <button className="button primary" type="submit" disabled={uploadState === "loading"}>
                <UploadCloud aria-hidden="true" size={16} />
                上传并索引
                <LoadingIcon active={uploadState === "loading"} />
              </button>
            </form>
            {uploadError && <p className="error-text">{uploadError}</p>}
            {taskState && (
              <div className="task-box" aria-live="polite">
                <div className="task-line">
                  <span>{taskState.file_name}</span>
                  <StatusBadge status={taskState.status} />
                </div>
                <dl className="metric-grid">
                  <div>
                    <dt>chunks</dt>
                    <dd>{taskState.chunk_count}</dd>
                  </div>
                  <div>
                    <dt>keys</dt>
                    <dd>{taskState.indexed_keys.length}</dd>
                  </div>
                </dl>
                <code>{taskState.task_id}</code>
                {taskState.error_message && <p className="error-text">{taskState.error_message}</p>}
                {pollError && <p className="error-text">{pollError}</p>}
              </div>
            )}
          </article>

          <article className="panel">
            <div className="panel-header">
              <FileSearch aria-hidden="true" size={20} />
              <div>
                <h2>知识检索</h2>
                <span>Redis Vector Search</span>
              </div>
            </div>
            <form className="stack" onSubmit={handleSearch}>
              <div className="field">
                <label htmlFor="search-query">Query</label>
                <textarea
                  id="search-query"
                  rows={3}
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                />
              </div>
              <div className="inline-fields">
                <div className="field compact">
                  <label htmlFor="search-top-k">top_k</label>
                  <input
                    id="search-top-k"
                    type="number"
                    min={1}
                    max={20}
                    value={searchTopK}
                    onChange={(event) => setSearchTopK(Number(event.target.value))}
                  />
                </div>
                <button className="button secondary" type="submit" disabled={searchState === "loading"}>
                  <Search aria-hidden="true" size={16} />
                  检索
                  <LoadingIcon active={searchState === "loading"} />
                </button>
              </div>
            </form>
            {searchError && <p className="error-text">{searchError}</p>}
            <SearchResults results={searchResults} />
          </article>

          <article className="panel">
            <div className="panel-header">
              <Plug aria-hidden="true" size={20} />
              <div>
                <h2>MCP 工具</h2>
                <span>Model Context Protocol</span>
              </div>
            </div>
            <button
              className="button secondary"
              type="button"
              onClick={handleLoadMcp}
              disabled={mcpState === "loading"}
            >
              <Plug aria-hidden="true" size={16} />
              加载 MCP 能力
              <LoadingIcon active={mcpState === "loading"} />
            </button>
            {mcpError && <p className="error-text">{mcpError}</p>}
            {mcpState === "success" && mcp && <McpCapabilities data={mcp} />}
          </article>

          <article className="panel">
            <div className="panel-header">
              <Activity aria-hidden="true" size={20} />
              <div>
                <h2>运行 Trace</h2>
                <span>Local JSONL Trace</span>
              </div>
            </div>
            <button
              className="button secondary"
              type="button"
              onClick={handleLoadTraces}
              disabled={traceState === "loading"}
            >
              <Activity aria-hidden="true" size={16} />
              加载最近运行
              <LoadingIcon active={traceState === "loading"} />
            </button>
            {traceError && <p className="error-text">{traceError}</p>}
            {traceState === "success" && <TraceList traces={traces} />}
          </article>
        </section>

        <section className="right-column" aria-label="Agent 运行">
          <article className="panel agent-panel">
            <div className="panel-header">
              <Bot aria-hidden="true" size={20} />
              <div>
                <h2>Agent Console</h2>
                <span>Workflow + Tools + Memory</span>
              </div>
            </div>
            <form className="stack" onSubmit={handleAgentRun}>
              <div className="inline-fields">
                <div className="field">
                  <label htmlFor="session-id">session_id</label>
                  <input
                    id="session-id"
                    value={sessionId}
                    onChange={(event) => setSessionId(event.target.value)}
                    maxLength={80}
                    spellCheck={false}
                  />
                </div>
                <div className="field compact">
                  <label htmlFor="agent-top-k">top_k</label>
                  <input
                    id="agent-top-k"
                    type="number"
                    min={1}
                    max={20}
                    value={agentTopK}
                    onChange={(event) => setAgentTopK(Number(event.target.value))}
                  />
                </div>
              </div>
              <label className="checkline" htmlFor="use-kb">
                <input
                  id="use-kb"
                  type="checkbox"
                  checked={useKnowledgeBase}
                  onChange={(event) => setUseKnowledgeBase(event.target.checked)}
                />
                <span>使用知识库</span>
              </label>
              <div className="field">
                <label htmlFor="agent-query">Query</label>
                <textarea
                  id="agent-query"
                  rows={7}
                  value={agentQuery}
                  onChange={(event) => setAgentQuery(event.target.value)}
                />
              </div>
              <button className="button primary" type="submit" disabled={agentState === "loading"}>
                <Send aria-hidden="true" size={16} />
                运行 Agent
                <LoadingIcon active={agentState === "loading"} />
              </button>
            </form>
            {agentError && <p className="error-text">{agentError}</p>}

            <div className="answer-layout">
              <section className="answer-section" aria-label="Agent 回答">
                <div className="section-title">
                  <BrainCircuit aria-hidden="true" size={16} />
                  <h3>Answer</h3>
                </div>
                {agentResponse ? (
                  <>
                    <div className="answer-meta">
                      <StatusBadge status={agentResponse.intent} />
                      <span>{agentResponse.used_knowledge_base ? "knowledge" : "tool/direct"}</span>
                      <span>{agentResponse.memory_used ? "memory on" : "memory off"}</span>
                    </div>
                    <pre className="answer-box">{agentResponse.answer}</pre>
                  </>
                ) : (
                  <p className="empty-text">暂无回答。</p>
                )}
              </section>

              <section className="answer-section" aria-label="Agent 步骤">
                <div className="section-title">
                  <Database aria-hidden="true" size={16} />
                  <h3>Steps</h3>
                </div>
                <AgentSteps response={agentResponse} />
              </section>
            </div>

            <section className="answer-section" aria-label="引用来源">
              <div className="section-title">
                <FileSearch aria-hidden="true" size={16} />
                <h3>Sources</h3>
              </div>
              <SourceList sources={agentResponse?.sources ?? []} />
            </section>
          </article>

          <article className="panel">
            <div className="panel-header">
              <BrainCircuit aria-hidden="true" size={20} />
              <div>
                <h2>记忆写入</h2>
                <span>Long-term profile</span>
              </div>
            </div>
            <div className="field">
              <label htmlFor="memory-text">Memory text</label>
              <input
                id="memory-text"
                value={memoryText}
                onChange={(event) => setMemoryText(event.target.value)}
              />
            </div>
            <button className="button secondary" type="button" onClick={handleMemoryUpdate}>
              {memoryState === "success" ? (
                <CheckCircle2 aria-hidden="true" size={16} />
              ) : memoryState === "error" ? (
                <XCircle aria-hidden="true" size={16} />
              ) : (
                <BrainCircuit aria-hidden="true" size={16} />
              )}
              写入记忆
              <LoadingIcon active={memoryState === "loading"} />
            </button>
            {memoryError && <p className="error-text">{memoryError}</p>}
          </article>

          <article className="panel">
            <div className="panel-header">
              <Send aria-hidden="true" size={20} />
              <div>
                <h2>流式对话</h2>
                <span>SSE Streaming</span>
              </div>
            </div>
            <form className="stack" onSubmit={handleStreamChat}>
              <div className="field">
                <label htmlFor="stream-input">Query</label>
                <textarea
                  id="stream-input"
                  rows={3}
                  value={streamInput}
                  onChange={(event) => setStreamInput(event.target.value)}
                />
              </div>
              <div className="inline-fields">
                <button className="button primary" type="submit" disabled={streamState === "loading"}>
                  <Send aria-hidden="true" size={16} />
                  流式发送
                  <LoadingIcon active={streamState === "loading"} />
                </button>
                {streamState === "loading" && (
                  <button className="button secondary" type="button" onClick={handleStopStream}>
                    <XCircle aria-hidden="true" size={16} />
                    停止
                  </button>
                )}
              </div>
            </form>
            {streamError && <p className="error-text">{streamError}</p>}
            {streamReasoning && (
              <details className="reasoning-box">
                <summary>思考过程（reasoning）</summary>
                <pre className="answer-box">{streamReasoning}</pre>
              </details>
            )}
            <section className="answer-section" aria-label="流式答案">
              <div className="section-title">
                <BrainCircuit aria-hidden="true" size={16} />
                <h3>Answer</h3>
                {streamFinishReason && (
                  <span className="answer-meta">finish: {streamFinishReason}</span>
                )}
              </div>
              {streamContent ? (
                <pre className="answer-box">{streamContent}</pre>
              ) : (
                <p className="empty-text">流式回答会在这里逐字显示。</p>
              )}
            </section>
          </article>

          <article className="panel">
            <div className="panel-header">
              <Bot aria-hidden="true" size={20} />
              <div>
                <h2>求职投递（人工介入）</h2>
                <span>Multi-Agent + HITL</span>
              </div>
            </div>
            <form className="stack" onSubmit={handleStartJobReview}>
              <div className="field">
                <label htmlFor="job-jd">岗位 JD</label>
                <textarea
                  id="job-jd"
                  rows={3}
                  value={jobJd}
                  onChange={(event) => setJobJd(event.target.value)}
                />
              </div>
              <button className="button primary" type="submit" disabled={jobState === "loading"}>
                <Bot aria-hidden="true" size={16} />
                开始分析匹配
                <LoadingIcon active={jobState === "loading"} />
              </button>
            </form>
            {jobError && <p className="error-text">{jobError}</p>}
            {jobResult && (
              <>
                <section className="answer-section" aria-label="简历摘要">
                  <div className="section-title">
                    <FileSearch aria-hidden="true" size={16} />
                    <h3>简历摘要</h3>
                  </div>
                  {jobResult.resume_summary ? (
                    <pre className="answer-box">{jobResult.resume_summary}</pre>
                  ) : (
                    <p className="empty-text">-</p>
                  )}
                </section>
                <section className="answer-section" aria-label="匹配分析">
                  <div className="section-title">
                    <Search aria-hidden="true" size={16} />
                    <h3>匹配分析</h3>
                  </div>
                  {jobResult.match_analysis ? (
                    <pre className="answer-box">{jobResult.match_analysis}</pre>
                  ) : (
                    <p className="empty-text">-</p>
                  )}
                </section>
                {jobResult.status === "interrupted" && (
                  <div className="field">
                    <label htmlFor="job-note">人工审核补充（可选）</label>
                    <input
                      id="job-note"
                      value={jobNote}
                      onChange={(event) => setJobNote(event.target.value)}
                      placeholder="例如：我也接触过 FastAPI 和 Redis"
                    />
                    <button
                      className="button secondary"
                      type="button"
                      onClick={handleResumeJobReview}
                      disabled={jobState === "loading"}
                    >
                      <CheckCircle2 aria-hidden="true" size={16} />
                      确认并生成投递材料
                      <LoadingIcon active={jobState === "loading"} />
                    </button>
                  </div>
                )}
                {jobResult.application_material && (
                  <section className="answer-section" aria-label="投递材料">
                    <div className="section-title">
                      <Send aria-hidden="true" size={16} />
                      <h3>投递材料</h3>
                    </div>
                    <pre className="answer-box">{jobResult.application_material}</pre>
                  </section>
                )}
                <p className="answer-meta">
                  status: {jobResult.status} · steps:{" "}
                  {jobResult.steps.map((step) => step.agent).join(" → ")}
                </p>
              </>
            )}
          </article>
        </section>
      </main>
    </div>
  );
}
