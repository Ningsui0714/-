(function connectBackend() {
  const studentId = window.localStorage.getItem("learning.student_id") || "STU-DEMO-001";
  const sessionId = window.localStorage.getItem("learning.session_id") || `WEB-${Date.now()}`;
  window.localStorage.setItem("learning.student_id", studentId);
  window.localStorage.setItem("learning.session_id", sessionId);

  let pendingRequests = 0;

  function emit(name, detail) {
    window.dispatchEvent(new CustomEvent(name, { detail }));
  }

  function setLoading(loading, operation = "") {
    pendingRequests = Math.max(0, pendingRequests + (loading ? 1 : -1));
    emit("workflow-loading", {
      loading: pendingRequests > 0,
      operation,
    });
  }

  function withIdentity(payload = {}) {
    return {
      student_id: studentId,
      session_id: sessionId,
      ...payload,
    };
  }

  function authToken() {
    // 优先使用后端注入的配置，其次本地存储（演示默认不配置则不携带）
    const explicit = window.__APP_TOKEN__;
    if (explicit) return explicit;
    try {
      return window.localStorage.getItem("app_api_token") || "";
    } catch {
      return "";
    }
  }

  function jsonHeaders(extra = {}) {
    const headers = { "Content-Type": "application/json", ...extra };
    const token = authToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }

  async function requestJson(path, options = {}) {
    const response = await window.fetch(path, {
      headers: jsonHeaders(options.headers),
      ...options,
    });
    const result = await response.json().catch(() => ({
      status: "error",
      user_message: "后端返回了无法解析的响应。",
    }));
    if (!response.ok) {
      const error = new Error(result.user_message || `请求失败：HTTP ${response.status}`);
      error.code = result.error_code || "REQUEST_FAILED";
      throw error;
    }
    return result;
  }

  async function withLoading(operation, task) {
    setLoading(true, operation);
    try {
      return await task();
    } catch (error) {
      emit("workflow-error", {
        operation,
        message: error instanceof Error ? error.message : "请求失败",
      });
      throw error;
    } finally {
      setLoading(false, operation);
    }
  }

  async function callWorkflow(workflow, payload) {
    const isResume = workflow === "post_test_review" && payload.resume_token;
    const endpoint = workflow === "continuous_learning"
      ? "/api/workflows/learning"
      : isResume
        ? "/api/workflows/review/resume"
        : "/api/workflows/review";
    return requestJson(endpoint, {
      method: "POST",
      body: JSON.stringify(withIdentity(payload)),
    });
  }

  async function runWorkflow(workflow, payload, applyResult = true) {
    const result = await withLoading(workflow, () => callWorkflow(workflow, payload));
    if (applyResult) window.personalizedLearningUI.applyWorkflowResult(result, { stream: true });
    return result;
  }

  async function explain(payload, applyResult = true) {
    const result = await withLoading(`explanation:${payload.scene || "unknown"}`, () => requestJson(
      "/api/explanations",
      {
        method: "POST",
        body: JSON.stringify(withIdentity(payload)),
      },
    ));
    if (applyResult) window.personalizedLearningUI.applyWorkflowResult(result, { stream: true });
    return result;
  }

  async function handleWorkflowRequest({ detail }) {
    const workflow = detail?.workflow;
    if (!workflow) return;
    try {
      await runWorkflow(workflow, detail.payload || {});
    } catch (error) {
      // withLoading already emitted a user-facing error.
    }
  }

  async function analyzeGoal(text) {
    return requestJson("/api/goal/analyze", {
      method: "POST",
      body: JSON.stringify(withIdentity({ text })),
    });
  }

  async function bootstrap() {
    try {
      const state = await withLoading("bootstrap", () => requestJson(
        `/api/bootstrap?student_id=${encodeURIComponent(studentId)}`,
      ));
      if (state.latest_review_result) {
        window.personalizedLearningUI.applyWorkflowResult(state.latest_review_result);
      }
      // The learning result owns the current lesson/path. Apply it last so a
      // historical review result cannot overwrite the active learning node.
      if (state.latest_learning_result) {
        window.personalizedLearningUI.applyWorkflowResult(state.latest_learning_result);
      }
      emit("app-bootstrap", state);
      emit("backend-ready", {
        mode: state.xingchen_mode,
        hasUpstream: state.has_upstream,
      });
      if (!state.has_upstream) {
        window.personalizedLearningUI.showMessage("等待上游测验或诊断结果后开始个性化教学");
      }
      return state;
    } catch (error) {
      return null;
    }
  }

  async function ingestUpstream(payload) {
    return withLoading("upstream", async () => {
      const result = await requestJson("/api/upstream/assessment-result", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (result.dispatched?.learning) {
        window.personalizedLearningUI.applyWorkflowResult(result.dispatched.learning);
      }
      if (result.dispatched?.review) {
        window.personalizedLearningUI.applyWorkflowResult(result.dispatched.review);
      }
      return result;
    });
  }

  function studentPath(resource) {
    return `/api/students/${encodeURIComponent(studentId)}/${resource}`;
  }

  async function getProfile() {
    return withLoading("profile", () => requestJson(studentPath("profile")));
  }

  async function getNotifications() {
    return withLoading("notifications", () => requestJson(studentPath("notifications")));
  }

  async function markNotificationRead(notificationId) {
    return withLoading("notification-read", () => requestJson(
      `${studentPath("notifications")}/${encodeURIComponent(notificationId)}/read`,
      { method: "POST", body: "{}" },
    ));
  }

  async function getRecords() {
    return withLoading("records", () => requestJson(studentPath("records")));
  }

  async function getSettings() {
    return withLoading("settings", () => requestJson(studentPath("settings")));
  }

  async function saveSettings(settings) {
    return withLoading("settings-save", () => requestJson(studentPath("settings"), {
      method: "POST",
      body: JSON.stringify(settings),
    }));
  }

  async function setFavorite(payload) {
    return withLoading("favorite", () => requestJson(studentPath("favorites"), {
      method: "POST",
      body: JSON.stringify(payload),
    }));
  }

  async function getSources(explanationSessionId) {
    return withLoading("sources", () => requestJson(
      `/api/explanations/${encodeURIComponent(explanationSessionId)}/sources?student_id=${encodeURIComponent(studentId)}`,
    ));
  }

  async function createPractice(payload) {
    return withLoading("practice-create", () => requestJson("/api/practice/questions", {
      method: "POST",
      body: JSON.stringify(withIdentity(payload)),
    }));
  }

  async function submitAttempt(questionInstanceId, answer) {
    return withLoading("practice-submit", () => requestJson(
      `/api/question-instances/${encodeURIComponent(questionInstanceId)}/attempts`,
      {
        method: "POST",
        body: JSON.stringify(withIdentity({ answer })),
      },
    ));
  }

  async function startDiagnosis(goal) {
    return withLoading("diagnosis-start", () => requestJson("/api/diagnosis/start", {
      method: "POST",
      body: JSON.stringify(withIdentity({ goal })),
    }));
  }

  async function submitDiagnosisAnswer(payload) {
    return withLoading("diagnosis-answer", () => requestJson("/api/diagnosis/answer", {
      method: "POST",
      body: JSON.stringify(withIdentity(payload)),
    }));
  }

  async function runCode(language, code) {
    return withLoading("code-run", () => requestJson("/api/code/run", {
      method: "POST",
      body: JSON.stringify(withIdentity({ language, code })),
    }));
  }

  async function searchKnowledge(query) {
    const params = new URLSearchParams({ q: query });
    return requestJson(`/api/knowledge/search?${params.toString()}`, { method: "GET" });
  }

  async function getBankQuestions(knowledgePointId = "") {
    const params = new URLSearchParams();
    if (knowledgePointId) params.set("knowledge_point_id", knowledgePointId);
    return requestJson(`/api/bank?${params.toString()}`, { method: "GET" });
  }

  async function checkBankAnswer(questionId, answer) {
    return withLoading("bank-answer", () => requestJson("/api/bank/answer", {
      method: "POST",
      body: JSON.stringify(withIdentity({ question_id: questionId, answer })),
    }));
  }

  async function chat(message) {
    return withLoading("chat", () => requestJson(
      "/api/chat",
      { method: "POST", body: JSON.stringify(withIdentity({ message })) },
    ));
  }

  async function getPortrait() {
    return withLoading("portrait", () => requestJson(studentPath("portrait")));
  }

  async function getGrowth() {
    return withLoading("growth", () => requestJson(studentPath("growth")));
  }

  async function askExplanation(explanationSessionId, payload) {
    return withLoading("ask", () => requestJson(
      `/api/explanations/${encodeURIComponent(explanationSessionId)}/ask`,
      { method: "POST", body: JSON.stringify(withIdentity(payload)) },
    ));
  }

  async function streamExplanation(explanationSessionId, handlers) {
    const url = `/api/explanations/${encodeURIComponent(explanationSessionId)}/stream?student_id=${encodeURIComponent(studentId)}`;
    const response = await window.fetch(url, { headers: jsonHeaders() });
    if (!response.ok || !response.body) {
      throw new Error(`讲解流不可用（HTTP ${response.status}）`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let done = false;
    while (!done) {
      const { done: streamDone, value } = await reader.read();
      if (streamDone) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let eventName = "message";
        let data = "";
        for (const line of rawEvent.split("\n")) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (data) {
          let parsed = {};
          try {
            parsed = JSON.parse(data);
          } catch (error) {
            // Ignore malformed frames and keep reading.
          }
          handlers.onEvent?.(eventName, parsed);
        }
      }
    }
  }
  window.addEventListener("workflow-request", handleWorkflowRequest);
  window.workflowBackend = Object.freeze({
    bootstrap,
    callWorkflow,
    runWorkflow,
    explain,
    ingestUpstream,
    getProfile,
    getNotifications,
    markNotificationRead,
    getRecords,
    getSettings,
    saveSettings,
    setFavorite,
    getSources,
    getPortrait,
    getGrowth,
    askExplanation,
    streamExplanation,
    createPractice,
    submitAttempt,
    startDiagnosis,
    submitDiagnosisAnswer,
    runCode,
    searchKnowledge,
    chat,
    getBankQuestions,
    checkBankAnswer,
    analyzeGoal,
    studentId,
    sessionId,
  });
  bootstrap();
})();
