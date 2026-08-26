const state = {
  page: "learning",
  learningMode: "text",
  learningStrategyLabel: "互动图文",
  reviewMode: "text",
  activeVideoResource: null,
  reviewVideoResource: null,
  toastTimer: null,
  reviewResumeToken: "",
  learningExplanationSessionId: "",
  reviewExplanationSessionId: "",
  currentTaskInstanceId: "",
  currentQuestionInstanceId: "",
  currentAttemptId: "",
  currentKnowledgePointId: "",
  currentKnowledgePointTitle: "",
  learningSources: [],
  reviewSources: [],
  favorite: false,
  diagnosisQuestions: [],
  diagnosisIndex: 0,
  diagnosisTotal: 0,
  diagnosisGoal: "competition",
  diagnosisRound: 0,
  diagnosisStats: { correct: 0, wrong: 0, skipped: 0, done: false },
  learningGoal: { goal_id: "GOAL-JAVA-001", goal_type: "course", goal_name: "完成 Java 面向对象成绩管理实训" },
  pathCollapsed: false,
  practiceQuestion: null,
  followUpSessionId: "",
  followUpSelection: "",
  followUpHistory: [],
  portraitData: null,
  streamActive: {},
};

const TRUSTED_EMBED_HOSTS = new Set([
  "player.bilibili.com",
  "www.youtube-nocookie.com",
]);

const WORKFLOW_EVENTS = Object.freeze({
  initializeLearning: "initialize_learning",
  continueLearning: "continue_learning",
  showExample: "show_example",
  showSteps: "show_steps",
  switchExplanation: "switch_explanation",
  requestVideo: "request_video",
  requestText: "request_text",
  checkFeedback: "check_feedback",
});

const WORKFLOW_STATUSES = Object.freeze({
  ok: "ok",
  needsClarification: "needs_clarification",
  endedByUser: "ended_by_user",
  needsWebSearch: "needs_web_search",
  knowledgeUnavailable: "knowledge_unavailable",
  systemRetryable: "system_retryable",
  fatalInternal: "fatal_internal",
});

const REVIEW_WORKFLOW_MODES = new Set([
  "review",
  // Historical persisted responses used this name before the unified Flow.
  "remediation",
]);

const modeLabels = {
  video: "视频教学",
  text: "互动图文",
};

const teachingStrategyLabels = {
  interactive_document: "互动图文",
  video_interactive: "视频教学",
  combined: "视频 + 互动图文",
  worked_example: "案例教学",
  step_by_step: "分步骤教学",
  execution_trace: "执行轨迹",
  scenario_tree: "情景树讲解",
  comparison: "对比讲解",
  steps_and_warning: "步骤与易错提醒",
};

const workflowModeToUiMode = {
  interactive_document: "text",
  video_interactive: "video",
  combined: "text",
  worked_example: "text",
  step_by_step: "text",
  execution_trace: "text",
  scenario_tree: "text",
  comparison: "text",
  steps_and_warning: "text",
};

const reviewContent = {
  q3: {
    title: "请补全 Student.averageScore()，缺考成绩为 null 时必须排除。",
    meta: "第 3 题 · 编码改错",
    knowledge: "知识点 KN_JAVA_ENCAPSULATION 封装与访问控制",
  },
  q6: {
    title: "当有效成绩集合为空时，averageScore() 应如何处理，避免空指针或除零？",
    meta: "第 6 题 · 代码分析",
    knowledge: "知识点 KN_JAVA_INHERITANCE 继承与方法重写",
  },
};

const stageChecks = {
  KN_JAVA_CLASS: {
    title: "创建对象的关键字",
    prompt: "在 main 方法中创建一个 Student 对象 stu，应使用哪个关键字？",
    options: [
      ["a", "A", "Student stu = struct Student();"],
      ["b", "B", "Student stu = new Student();"],
      ["c", "C", "Student stu = create Student();"],
    ],
    correctAnswer: "b",
    incorrectFeedback: "Java 使用 new 关键字调用构造器完成对象创建。",
  },
  KN_JAVA_ENCAPSULATION: {
    title: "私有字段的访问方式",
    prompt: "Student 类的成绩数组被声明为 private，外部代码应通过什么方式读取有效成绩？",
    options: [
      ["a", "A", "直接访问 stu.scores"],
      ["b", "B", "调用 getter（如 getScores()）获取只读视图"],
      ["c", "C", "把 scores 改为 public 静态字段"],
    ],
    correctAnswer: "b",
    incorrectFeedback: "私有字段必须通过类提供的公共方法访问，不能暴露内部数组引用。",
  },
  KN_JAVA_INHERITANCE: {
    title: "方法重写的注解",
    prompt: "子类 StudentWithBonus 覆盖父类的 averageScore() 方法时，应在方法上标注什么注解？",
    options: [
      ["a", "A", "@overload"],
      ["b", "B", "@Override"],
      ["c", "C", "@inherit"],
    ],
    correctAnswer: "b",
    incorrectFeedback: "重写父类方法用 @Override 注解，编译器会检查签名是否真的覆盖了父类方法。",
  },
  KN_JAVA_POLYMORPHISM: {
    title: "实现接口的关键字",
    prompt: "一个类同时实现多个接口（如 Runnable 与 Comparable），应使用哪个关键字？",
    options: [
      ["a", "A", "extends"],
      ["b", "B", "implements"],
      ["c", "C", "uses"],
    ],
    correctAnswer: "b",
    incorrectFeedback: "类实现接口用 implements，可同时实现多个接口；继承类才用 extends。",
  },
  KN_JAVA_COLLECTION: {
    title: "集合的添加方法",
    prompt: "向 ArrayList<String> 集合末尾添加一个元素，应调用哪个方法？",
    options: [
      ["a", "A", "push(item)"],
      ["b", "B", "add(item)"],
      ["c", "C", "insert(item)"],
    ],
    correctAnswer: "b",
    incorrectFeedback: "List 接口用 add() 添加元素；push() 是栈/队列风格的接口方法。",
  },
  KN_JAVA_EXCEPTION: {
    title: "异常捕获的结构",
    prompt: "处理可能抛出的 IOException，正确的捕获结构是：",
    options: [
      ["a", "A", "catch { ... }"],
      ["b", "B", "try { ... } catch (IOException e) { ... }"],
      ["c", "C", "throw IOException()"],
    ],
    correctAnswer: "b",
    incorrectFeedback: "try 包裹可能抛异常的代码，catch 按异常类型处理；throw 是主动抛出而非捕获。",
  },
  KN_JAVA_IO: {
    title: "读取文本文件的类",
    prompt: "按行读取文本文件，常用哪个类组合？",
    options: [
      ["a", "A", "FileInputStream 直接读"],
      ["b", "B", "BufferedReader + FileReader"],
      ["c", "C", "System.in 读取"],
    ],
    correctAnswer: "b",
    incorrectFeedback: "BufferedReader.readLine() 搭配 FileReader 按行读取文本；字节流不直接处理字符。",
  },
};

const defaultStageCheck = stageChecks.KN_JAVA_ENCAPSULATION;

async function requestLearning(eventType, payload = {}, applyResult = true) {
  return window.workflowBackend.runWorkflow("continuous_learning", {
    event_type: eventType,
    // 携带当前学习目标：目标驱动路径生成（后端 path_for_learning_goal）
    learning_goal: state.learningGoal || {
      goal_id: "GOAL-JAVA-001",
      goal_type: "course",
      goal_name: "完成 Java 面向对象成绩管理实训",
    },
    ...payload,
  }, applyResult);
}

function hasRenderableLearningOutcome(result) {
  if (!result || result.status !== WORKFLOW_STATUSES.ok) return false;
  const blocks = Array.isArray(result.content_blocks)
    ? result.content_blocks.filter((block) => block && (block.content || block.items?.length))
    : [];
  if (!blocks.length) return false;
  const nextId = String(result.path_update?.next_knowledge_point_id || "").trim();
  if (!nextId) return true;
  const renderedId = String(result.knowledge_point_id || "").trim()
    || String(result.learning_path?.current_knowledge_point_id || "").trim();
  return renderedId === nextId;
}

function learningOutcomeUnavailable(result) {
  return result?.user_message
    || result?.error_message
    || "答案已核验，但下一节讲解内容尚未生成，请稍后重试。此次作答不会重复计分。";
}

async function requestReview(payload) {
  return window.workflowBackend.runWorkflow("post_test_review", payload);
}

function createElement(tagName, className = "", text = "") {
  const element = tagName === "svg"
    ? document.createElementNS("http://www.w3.org/2000/svg", "svg")
    : document.createElement(tagName);
  if (className) element.setAttribute("class", className);
  if (text) element.textContent = text;
  return element;
}

// 富文本渲染：marked（markdown）+ KaTeX（$..$ / $$..$$ 公式）
// 安全边界：只渲染工作流/后端产出的受控内容；原始 HTML 一律丢弃，链接仅允许 http(s)
function initRichText() {
  if (!window.marked) return;
  const renderer = new window.marked.Renderer();
  renderer.html = () => "";
  renderer.link = (href, title, text) => {
    const safe = String(href || "").startsWith("http://") || String(href || "").startsWith("https://")
      ? href
      : "";
    if (!safe) return text;
    const escaped = window.marked.parseInline(text);
    // href 属性值必须转义引号，防止 [x](http://a"onclick=...) 注入
    const attr = String(safe).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<a href="${attr}" target="_blank" rel="noopener noreferrer">${escaped}</a>`;
  };
  window.marked.setOptions({
    renderer,
    breaks: true,
    gfm: true,
    headerIds: false,
    mangle: false,
  });
}

function renderRichText(source) {
  if (!source) return "";
  const text = String(source);
  if (!window.marked) return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  // marked 先渲染 markdown（$...$ 公式原样保留），再对输出 HTML 做 KaTeX 替换，
  // 避免占位符被 markdown 语法（如 __xx__ 强调）误解析
  let html = window.marked.parse(text);
  // 块级公式 $$...$$（独立成段时被 <p> 包裹）
  html = html.replace(/<p>\$\$([\s\S]+?)\$\$<\/p>/g, (match, expr) => {
    try {
      return window.katex.renderToString(expr.trim(), {
        displayMode: true,
        throwOnError: false,
      });
    } catch {
      return match;
    }
  });
  // 行内公式 $...$
  html = html.replace(/\$([^$\n]+?)\$/g, (match, expr) => {
    const candidate = expr.trim();
    if (!candidate || /\$\$/.test(match)) return match;
    try {
      return window.katex.renderToString(candidate, { throwOnError: false });
    } catch {
      return match;
    }
  });
  return html;
}

function renderRichTextElement(source) {
  const wrapper = createElement("div", "rich-text");
  wrapper.innerHTML = renderRichText(source);
  return wrapper;
}

function safeHttpUrl(value) {
  const rawValue = String(value || "").trim();
  if (!rawValue) return "";
  try {
    const url = new URL(rawValue, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function safeEmbedUrl(value) {
  const url = safeHttpUrl(value);
  if (!url) return "";
  return TRUSTED_EMBED_HOSTS.has(new URL(url).hostname) ? url : "";
}

function videoResources(resources) {
  return Array.isArray(resources)
    ? resources.filter((resource) => resource?.type === "video" && safeHttpUrl(resource.url))
    : [];
}

function documentResources(resources) {
  return Array.isArray(resources)
    ? resources.filter((resource) => resource?.type === "document" && safeHttpUrl(resource.url))
    : [];
}

function buildDocumentCard(doc) {
  const card = createElement("article", "document-card");
  const heading = createElement("div", "document-card-heading");
  heading.append(createElement("strong", "", doc.title || "联网官方文档"));
  const meta = [
    doc.source ? `来源：${doc.source}` : "",
    doc.provider ? `检索：${doc.provider}` : "",
  ].filter(Boolean);
  heading.append(createElement("span", "document-meta", meta.join(" · ") || "白名单官方来源"));
  card.append(heading);
  const content = String(doc.description || doc.content || "").trim();
  if (content) card.append(createElement("p", "document-content", content));
  const url = safeHttpUrl(doc.url);
  if (url) {
    const link = createElement("a", "document-link", "打开原文");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    card.append(link);
  }
  return card;
}

function renderLearningDocuments(resources) {
  const board = document.querySelector("#document-summary");
  const list = document.querySelector("#document-list");
  const gap = document.querySelector("#document-gap");
  const count = document.querySelector("#document-board-count");
  const docs = documentResources(resources);
  list.replaceChildren();
  if (!docs.length) {
    board.hidden = true;
    return;
  }
  board.hidden = false;
  gap.hidden = true;
  count.textContent = `${docs.length} 篇`;
  docs.forEach((doc) => list.append(buildDocumentCard(doc)));
}

function renderReviewDocuments(resources) {
  const section = document.querySelector("#review-documents");
  const list = document.querySelector("#review-document-list");
  const gap = document.querySelector("#review-document-gap");
  const docs = documentResources(resources);
  list.replaceChildren();
  if (!docs.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  gap.hidden = true;
  docs.forEach((doc) => list.append(buildDocumentCard(doc)));
}

function renderLearningPath(path) {
  const items = Array.isArray(path?.items) ? path.items : [];
  if (!items.length) return;
  const list = document.querySelector("#path-list");
  list.replaceChildren();
  document.querySelector("#path-count").textContent = `${items.length} 个学习节点`;
  let currentPosition = 1;
  items.forEach((item, index) => {
    const status = item.status === "completed" ? "completed" : item.status === "current" ? "current" : "locked";
    if (status === "current") currentPosition = index + 1;
    const listItem = createElement("li", `path-item ${status}`);
    const button = createElement("button");
    button.type = "button";
    button.dataset.lesson = String(index);
    button.dataset.knowledgePointId = item.knowledge_point_id || "";
    button.dataset.knowledgePointName = item.knowledge_point_name || "";
    button.dataset.knowledgeType = item.knowledge_type || "conceptual";
    button.dataset.mastery = String(item.mastery || 0);
    button.disabled = status === "locked";
    if (status === "current") button.setAttribute("aria-current", "step");
    const stateElement = createElement("span", "path-state");
    stateElement.textContent = status === "completed" ? "\u2713" : status === "locked" ? "\u00b7" : String(index + 1).padStart(2, "0");
    const copy = createElement("span", "path-copy");
    const typeLabel = item.knowledge_type === "code" ? "代码" : "概念";
    copy.append(createElement("small", "", status === "current" ? `${typeLabel}` : `${String(index + 1).padStart(2, "0")} · ${typeLabel}`));
    copy.append(createElement("strong", "", item.knowledge_point_name || `学习节点 ${index + 1}`));
    const duration = createElement(
      "span",
      "path-duration",
      status === "completed" ? "完成" : status === "current" ? "学习中" : "待解锁",
    );
    button.append(stateElement, copy, duration);
    listItem.append(button);
    list.append(listItem);
  });
  document.querySelector("#lesson-position").textContent = lessonPositionText(items.length);
}

function lessonPositionText(total = 0) {
  const items = Array.isArray(state.learningPath?.items) ? state.learningPath.items : [];
  const lessonId = state.currentKnowledgePointId || "";
  const idx = items.findIndex((item) => item?.knowledge_point_id === lessonId);
  const pos = idx >= 0
    ? idx + 1
    : (items.findIndex((item) => item?.status === "current") + 1) || 1;
  return `第 ${pos} 节 / 共 ${total || items.length} 节`;
}

function buildContentSection(block, index) {
  const section = createElement("section", `content-section block-${block.type || "text"}`);
  section.append(createElement("div", "section-index", String(index + 1).padStart(2, "0")));
  const content = createElement("div", "wide-content");
  content.append(createElement("h3", "", block.title || `讲解内容 ${index + 1}`));
  // 兼容 items 与 steps 两种字段（v4/v5 校验均接受 steps 作为步骤列表别名）
  const steps =
    (Array.isArray(block.items) && block.items.length && block.items) ||
    (Array.isArray(block.steps) && block.steps.length && block.steps) ||
    null;
  if (steps) {
    const list = createElement("ol", "generated-step-list");
    steps.forEach((item) => list.append(createElement("li", "", String(item))));
    content.append(list);
  } else {
    content.append(renderRichTextElement(block.content || block.text || block.description || ""));
  }
  if (block.source) content.append(createElement("small", "block-source", `来源：${block.source}`));
  section.append(content);
  return section;
}

function renderContentBlocks(blocks, emptyMessage = "当前节点暂未返回讲解内容，请稍后重试。") {
  const container = document.querySelector("#content-blocks");
  container.replaceChildren();
  if (!Array.isArray(blocks) || !blocks.length) {
    const section = createElement("section", "content-section block-notice");
    section.append(createElement("div", "section-index", "01"));
    const content = createElement("div", "wide-content");
    content.append(createElement("h3", "", "讲解内容暂未就绪"));
    content.append(createElement("p", "", emptyMessage));
    section.append(content);
    container.append(section);
    return;
  }
  blocks.forEach((block, index) => container.append(buildContentSection(block, index)));
}

function renderResources(resources, resourceGap = "") {
  const container = document.querySelector("#resource-summary");
  container.replaceChildren(createElement("small", "", "联网与知识库资源"));
  const usableResources = Array.isArray(resources) ? resources : [];
  usableResources.forEach((resource) => {
    const row = createElement("div", "resource-row");
    const icon = createElement("span", `resource-icon ${resource.type === "video" ? "" : "document"}`);
    icon.textContent = resource.type === "video" ? "▶" : "▤";
    const copy = createElement("div");
    copy.append(createElement("strong", "", resource.title || "学习资源"));
    const sourceParts = [
      resource.source ? `来源：${resource.source}` : "",
      resource.provider ? `检索：${resource.provider}` : "",
      resource.segment || "",
    ].filter(Boolean);
    copy.append(createElement("span", "", sourceParts.join(" · ") || "课程资源库"));
    if (resource.reason || resource.description) {
      copy.append(createElement("span", "", resource.reason || resource.description));
    }
    const resourceUrl = safeHttpUrl(resource.url);
    if (resourceUrl) {
      const link = createElement("a", "resource-link", "打开资源");
      link.href = resourceUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.addEventListener("click", (event) => event.stopPropagation());
      copy.append(link);
    }
    if (resource.type === "video") {
      // 点击视频行直接内嵌播放（B 站官方 embed 播放器）
      row.classList.add("resource-video-row");
      row.addEventListener("click", () => {
        state.activeVideoResource = resource;
        playVideo();
      });
    }
    row.append(icon, copy);
    container.append(row);
  });
  if (!usableResources.length || resourceGap) {
    container.append(createElement("p", "resource-gap", resourceGap || "当前讲解不需要额外资源。"));
  }
}

function renderLearningVideo(resources, resourceGap = "") {
  const resource = videoResources(resources)[0] || null;
  state.activeVideoResource = resource;
  const placeholder = document.querySelector("#media-placeholder");
  const frame = document.querySelector("#video-frame");
  const title = document.querySelector("#media-title");
  const segment = document.querySelector("#media-segment");
  const detailButton = document.querySelector("#media-detail-button");
  frame.src = "about:blank";
  frame.hidden = true;
  placeholder.hidden = false;
  if (detailButton) detailButton.hidden = true;
  if (!resource) {
    title.textContent = "暂无可核验的联网教学视频";
    segment.textContent = resourceGap || "系统不会生成或展示没有来源的视频链接";
    return;
  }
  title.textContent = resource.title || "联网教学视频";
  segment.textContent = resource.segment || resource.reason || "根据当前薄弱知识点推荐";
  // 可内嵌（B 站/YouTube）→ iframe 播放器；否则保留卡片 + 详情按钮，绝不自动跳转
  const embedUrl = safeEmbedUrl(resource.embed_url);
  if (embedUrl) {
    document.querySelector("#media-stage").hidden = false;
    frame.src = embedUrl;
    frame.hidden = false;
    placeholder.hidden = true;
  } else if (detailButton) {
    detailButton.hidden = false;
  }
}

function openVideoDetail(resource) {
  const dialog = document.querySelector("#video-detail-dialog");
  if (!dialog) return;
  const title = document.querySelector("#video-detail-title");
  const source = document.querySelector("#video-detail-source");
  const desc = document.querySelector("#video-detail-desc");
  const open = document.querySelector("#video-detail-open");
  if (title) title.textContent = resource.title || "教学视频";
  if (source) {
    const parts = [
      resource.source ? `来源：${resource.source}` : "",
      resource.source_domain ? `站点：${resource.source_domain}` : "",
      resource.provider ? `检索：${resource.provider}` : "",
    ].filter(Boolean);
    source.textContent = parts.join(" · ") || "联网检索视频";
  }
  if (desc) {
    desc.textContent = resource.segment || resource.reason || resource.description || "该视频来自外部教学站点，可在来源网站中查看完整内容。";
    desc.hidden = !desc.textContent;
  }
  const url = safeHttpUrl(resource.url);
  if (open) {
    if (url) {
      open.href = url;
      open.hidden = false;
    } else {
      open.hidden = true;
      open.removeAttribute("href");
    }
  }
  if (window.lucide) window.lucide.createIcons();
  dialog.showModal();
}

function renderReviewVideo(resources, resourceGap = "") {
  const resource = videoResources(resources)[0] || null;
  state.reviewVideoResource = resource;
  const card = document.querySelector("#review-video-card");
  card.hidden = state.reviewMode !== "video";
  document.querySelector("#review-video-title").textContent = resource?.title || "暂无可核验视频";
  document.querySelector("#review-video-source").textContent = resource
    ? `来源：${resource.source || resource.source_domain || "联网搜索"}${resource.provider ? ` · 检索：${resource.provider}` : ""}`
    : "未获得带来源的视频链接";
  document.querySelector("#review-video-reason").textContent = resource?.reason || resource?.description || resourceGap || "继续使用当前图文讲解。";
  const detail = document.querySelector("#review-video-detail");
  if (detail) detail.hidden = !resource;
}

function renderLearningResult(result, options = {}) {
  const plan = result.teaching_plan || {};
  const uiMode = workflowModeToUiMode[plan.primary_mode] || "text";
  const strategyLabel = teachingStrategyLabels[plan.primary_mode] || modeLabels[uiMode] || "当前教学方式";
  const modeResources = (Array.isArray(result.resources) ? result.resources : []).filter(
    (resource) => uiMode === "video" ? resource?.type === "video" : resource?.type !== "video",
  );
  const currentPathItem = Array.isArray(result.learning_path?.items)
    ? result.learning_path.items.find((item) => item?.status === "current")
    : null;
  const currentKnowledgePointId = result.knowledge_point_id || currentPathItem?.knowledge_point_id || "";
  const currentKnowledgePointTitle = result.lesson_title || currentPathItem?.knowledge_point_name || "当前个性化课程";
  document.querySelector("#lesson-heading").textContent = currentKnowledgePointTitle;
  document.querySelector("#lesson-objective").textContent = result.lesson_objective || "完成当前知识点学习。";
  document.querySelector("#lesson-topic-code").textContent = currentKnowledgePointId || "CURRENT_TOPIC";
  state.currentKnowledgePointId = currentKnowledgePointId || state.currentKnowledgePointId;
  state.currentKnowledgePointTitle = currentKnowledgePointTitle || state.currentKnowledgePointTitle;
  state.learningPath = result.learning_path || state.learningPath;
  const positionEl = document.querySelector("#lesson-position");
  if (positionEl) positionEl.textContent = lessonPositionText();
  state.currentTaskInstanceId = result.task_instance_id || state.currentTaskInstanceId;
  state.learningExplanationSessionId = result.explanation_session_id || state.learningExplanationSessionId;
  // 学习讲解会话即追问会话：同步设置，保证"展开内容后可追问"链路可用
  if (result.explanation_session_id) state.followUpSessionId = result.explanation_session_id;
  state.learningSources = Array.isArray(result.source_references) ? result.source_references : [];
  document.querySelector("#diagnosis-copy").textContent = result.content_blocks?.[0]?.content || "本节内容由上游薄弱点诊断触发。";
  document.querySelector("#strategy-heading").textContent = `为什么采用${strategyLabel}`;
  document.querySelector("#strategy-reason").textContent = plan.reason || "系统依据掌握度和历史效果选择本轮讲解方式。";
  const tags = document.querySelector("#strategy-tags");
  tags.replaceChildren(
    createElement("span", "", plan.depth === "guided" ? "引导深度" : "标准深度"),
    createElement("span", "", strategyLabel),
    createElement("span", "", result.event_type || "学习事件"),
  );
  const progress = Number(result.path_update?.progress ?? result.learning_path?.progress);
  if (Number.isFinite(progress)) {
    const clamped = Math.max(0, Math.min(100, progress));
    document.querySelector("#overall-progress-value").textContent = `${clamped}%`;
    document.querySelector("#overall-progress-bar").style.width = `${clamped}%`;
    const goalProgress = document.querySelector(".goal-progress");
    goalProgress.setAttribute("aria-valuenow", String(clamped));
  }
  renderLearningPath(result.learning_path);
  const streamSessionId = result.explanation_session_id || "";
  const { stream = false } = options;
  if (stream && streamSessionId && Array.isArray(result.content_blocks) && result.content_blocks.length) {
    renderStreamingPlaceholder("learning");
    void consumeExplanationStream(streamSessionId, "learning", result);
  } else {
    renderContentBlocks(result.content_blocks, result.user_message || result.resource_gap);
  }
  renderLearningVideo(modeResources, result.resource_gap);
  renderLearningDocuments(modeResources);
  if (state.settings?.auto_play_video && uiMode === "video" && state.activeVideoResource) {
    const embedUrl = safeEmbedUrl(state.activeVideoResource.embed_url);
    if (embedUrl) playVideo();
  }
  renderResources(modeResources, result.resource_gap);
  const sourceTitles = state.learningSources.map((source) => source.title).filter(Boolean);
  const legacySources = Array.isArray(result.sources)
    ? result.sources.map((source) => typeof source === "string" ? source : source.title).filter(Boolean)
    : [];
  document.querySelector("#source-summary").textContent = `依据：${sourceTitles.join("、") || legacySources.join("、") || "课程知识库与上游诊断"}`;
  setLearningMode(uiMode, strategyLabel);
  lucide.createIcons();
}

function renderReviewResult(result, options = {}) {
  const question = result.question_snapshot || {};
  const attempt = result.current_attempt || {};
  const evaluation = result.validated_evaluation || {};
  const target = result.target_error || evaluation.error_points?.[0] || {};
  const deliveryMode = result.delivery_mode || result.teaching_strategy?.delivery_mode || "interactive_document";
  const uiMode = workflowModeToUiMode[deliveryMode] || "text";
  const modeResources = (Array.isArray(result.resources) ? result.resources : []).filter(
    (resource) => uiMode === "video" ? resource?.type === "video" : resource?.type !== "video",
  );
  setReviewMode(uiMode, false);
  const workspace = document.querySelector("#question-workspace");
  workspace.querySelector("h2").textContent = question.question_text || "当前测验题目";
  const meta = workspace.querySelectorAll(".question-meta span");
  meta[0].textContent = `题目 ${question.question_id || "--"}`;
  meta[1].textContent = `知识点 ${target.knowledge_point_id || "待确认"}`;
  workspace.querySelector(".student-answer code").textContent = attempt.student_answer || "未提供作答内容";
  workspace.querySelector(".student-answer p").textContent = target.student_evidence || target.diagnosis || "系统已定位错误证据。";
  workspace.querySelector(".expected-answer code").textContent = target.expected_behavior || "请按照题目要求完成操作。";
  workspace.querySelector(".expected-answer b").textContent = target.knowledge_point_name || "正确要求";
  workspace.querySelector(".review-source span").textContent = `诊断依据：${target.error_id || "上游测验诊断"}`;

  const score = Number(evaluation.score);
  const maxScore = Number(evaluation.max_score);
  if (Number.isFinite(score)) document.querySelector("#review-score").textContent = String(score);
  if (Number.isFinite(maxScore)) document.querySelector("#review-max-score").textContent = String(maxScore);
  const errors = Array.isArray(evaluation.error_points) ? evaluation.error_points : [];
  document.querySelector("#review-weak-count").textContent = `发现 ${Math.max(1, errors.length)} 个薄弱知识点`;

  document.querySelector("#explanation-panel .explanation-heading h2").textContent = target.knowledge_point_name || "个性化错误讲解";
  const flow = document.querySelector("#explanation-panel .explanation-flow");
  flow.replaceChildren();
  const steps = Array.isArray(result.explanation_steps) && result.explanation_steps.length
    ? result.explanation_steps
    : [{ title: "针对性讲解", content: result.personalized_explanation || "已生成本题讲解。" }];
  const streamSessionId = result.explanation_session_id || "";
  const { stream = false } = options;
  if (stream && streamSessionId && steps.length) {
    renderStreamingPlaceholder("review");
    void consumeExplanationStream(streamSessionId, "review", result);
  } else {
    steps.slice(0, 4).forEach((step, index) => flow.append(buildFlowStep(step, index)));
  }
  document.querySelector("#explanation-panel .retry-hint p").textContent = result.retry_guidance || "根据讲解重新检查原答案。";
  renderReviewVideo(modeResources, result.resource_gap);
  renderReviewDocuments(modeResources);
  state.currentKnowledgePointId = target.knowledge_point_id || "";
  state.currentKnowledgePointTitle = target.knowledge_point_name || "当前知识点";
  state.currentTaskInstanceId = result.task_instance_id || state.currentTaskInstanceId;
  state.currentQuestionInstanceId = result.question_instance_id || question.question_instance_id || state.currentQuestionInstanceId;
  state.currentAttemptId = result.attempt_id || state.currentAttemptId;
  state.reviewExplanationSessionId = result.explanation_session_id || state.reviewExplanationSessionId;
  state.reviewSources = Array.isArray(result.source_references) ? result.source_references : [];
  lucide.createIcons();
}

function applyWorkflowResult(result, options = {}) {
  if (!result || typeof result !== "object") return;

  if (result.status === WORKFLOW_STATUSES.needsClarification) {
    state.reviewResumeToken = result.resume_token || "";
    const message = result.user_message || result.clarification_question;
    if (message) {
      document.querySelector("#clarification-dialog .clarification-copy").textContent = message;
    }
    document.querySelector("#clarification-input").value = "";
    if (!document.querySelector("#clarification-dialog").open) {
      document.querySelector("#clarification-dialog").showModal();
    }
    return;
  }

  if (result.status === WORKFLOW_STATUSES.endedByUser) {
    if (document.querySelector("#clarification-dialog").open) {
      document.querySelector("#clarification-dialog").close();
    }
    const pending = document.querySelector('[data-question="q8"]');
    pending.querySelector("strong").textContent = "本题讲解已结束";
    pending.querySelector("small").textContent = "用户无法提供缺失信息";
    showToast(result.user_message || "本次工作流已按用户选择结束");
    return;
  }

  if (result.status === WORKFLOW_STATUSES.ok) {
    if (result.workflow_mode === "learning") {
      renderLearningResult(result, options);
    } else if (REVIEW_WORKFLOW_MODES.has(result.workflow_mode)) {
      renderReviewResult(result, options);
    } else {
      showToast("工作流返回了无法识别的页面类型，请稍后重试。");
    }
    if (state.reviewResumeToken) {
      state.reviewResumeToken = "";
      const pending = document.querySelector('[data-question="q8"]');
      pending.classList.remove("pending");
      pending.querySelector("strong").textContent = "题目信息已补充";
      pending.querySelector("small").textContent = "工作流已恢复并继续处理";
      pending.querySelector(".question-number").innerHTML = '<i data-lucide="check"></i>';
      lucide.createIcons();
    }
    return;
  }

  if (result.status === WORKFLOW_STATUSES.needsWebSearch) {
    showToast(result.user_message || "当前知识点需要联网检索依据，请稍后重试。");
    return;
  }

  if (result.status === WORKFLOW_STATUSES.knowledgeUnavailable) {
    showToast(result.user_message || "当前知识点暂时没有可用知识依据，请换一个切入点或联系老师补充教学资料。");
    return;
  }

  if (result.status === WORKFLOW_STATUSES.systemRetryable) {
    showToast(result.user_message || "内容生成暂时失败，请稍后重试。");
    return;
  }

  if (result.status === WORKFLOW_STATUSES.fatalInternal) {
    showToast(result.user_message || result.error_message || "系统处理失败，请刷新后重试。");
    return;
  }

  showToast(result.user_message || result.error_message || "工作流暂时无法完成，请稍后重试");
}

function showToast(message, type = "success") {
  const toast = document.querySelector("#toast");
  toast.querySelector("span").textContent = message;
  const icon = toast.querySelector("i");
  const iconNames = { success: "circle-check", info: "info", warning: "triangle-alert" };
  if (icon) icon.setAttribute("data-lucide", iconNames[type] || "circle-check");
  toast.classList.remove("info", "warning");
  if (type !== "success") toast.classList.add(type);
  if (window.lucide) window.lucide.createIcons();
  toast.classList.add("show");
  window.clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => toast.classList.remove("show"), 2600);
}

function setPage(page) {
  state.page = page;
  document.querySelectorAll(".page").forEach((element) => {
    element.classList.toggle("active", element.id === `${page}-page`);
  });
  document.querySelectorAll("[data-page-target]").forEach((button) => {
    const active = button.dataset.pageTarget === page;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  const workspace = document.querySelector(".workspace");
  if (workspace) workspace.scrollTo({ top: 0, behavior: "smooth" });
  if (page === "records") loadRecords();
  if (page === "portrait") loadPortrait();
  if (page === "growth") loadGrowth();
  if (page === "settings") loadSettings();
  if (page === "diagnosis") loadDiagnosis();
  if (page === "bank") loadBank();
  if (page === "profile") loadProfilePage();
}

function setLearningMode(mode, strategyLabel = modeLabels[mode]) {
  state.learningMode = mode;
  state.learningStrategyLabel = strategyLabel || modeLabels[mode] || "当前教学方式";
  document.querySelectorAll("[data-learning-mode]").forEach((button) => {
    const active = button.dataset.learningMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  document.querySelector("#media-stage").hidden = mode === "text";
  document.querySelector("#lesson-document").hidden = mode === "video";
  document.querySelector("#document-summary").hidden = mode === "video";
  document.querySelector("#current-mode-label").textContent = state.learningStrategyLabel;
}

function setReviewMode(mode, announce = false) {
  state.reviewMode = mode;
  document.querySelectorAll("[data-review-mode]").forEach((button) => {
    const active = button.dataset.reviewMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const heading = document.querySelector("#explanation-panel .explanation-heading h2");
  const card = document.querySelector("#review-video-card");
  card.hidden = mode !== "video";
  heading.textContent = mode === "video" ? "与本题错误相关的视频讲解" : "问题定位与分步骤讲解";
  if (announce) {
    if (mode === "video" && !state.reviewVideoResource) {
      showToast("本题暂未检索到带明确来源的视频，图文讲解仍然保留");
    } else {
      showToast(mode === "video" ? "已展示联网视频及其来源" : "已切换到分步骤图文讲解");
    }
  }
}

function setControlPending(control, pending) {
  control.disabled = pending;
  control.setAttribute("aria-busy", String(pending));
}

async function changeLearningMode(mode, control) {
  if (mode === state.learningMode) return;
  const previousMode = state.learningMode;
  const previousLabel = state.learningStrategyLabel;
  // 预览选中态：点击即反馈，避免请求期间"点了没反应"
  setLearningMode(mode, modeLabels[mode] || "切换中");
  const eventType = mode === "video"
    ? WORKFLOW_EVENTS.requestVideo
    : mode === "text"
      ? WORKFLOW_EVENTS.requestText
      : WORKFLOW_EVENTS.switchExplanation;
  setControlPending(control, true);
  try {
    const result = await window.workflowBackend.explain({
      scene: "learn",
      event_type: eventType,
      requested_mode: mode,
      requested_delivery_mode: mode,
      task_instance_id: state.currentTaskInstanceId,
      source_explanation_session_id: state.learningExplanationSessionId,
    });
    if (result.status === WORKFLOW_STATUSES.ok) {
      showToast(`已采用服务返回的${state.learningStrategyLabel}`);
    } else {
      // 非 ok 状态（如 needs_web_search / system_retryable）由 applyWorkflowResult 提示
      setLearningMode(previousMode, previousLabel);
    }
  } catch (error) {
    // 请求失败：回滚到之前的选中态
    setLearningMode(previousMode, previousLabel);
  } finally {
    setControlPending(control, false);
  }
}

async function requestReviewExplanation(options, control) {
  setControlPending(control, true);
  try {
    const result = await window.workflowBackend.explain({
      scene: "re_explain",
      source_explanation_session_id: state.reviewExplanationSessionId,
      task_instance_id: state.currentTaskInstanceId,
      question_instance_id: state.currentQuestionInstanceId,
      attempt_id: state.currentAttemptId,
      requested_delivery_mode: options.requestedMode || state.reviewMode,
      avoid_explanation_type: options.avoidType || "previous",
    });
    if (result.status === WORKFLOW_STATUSES.ok) {
      showToast(options.message || "已生成新的讲解会话");
    }
  } catch (error) {
    // Keep the previous explanation and selection when the backend fails.
  } finally {
    setControlPending(control, false);
  }
}

function playVideo() {
  const resource = state.activeVideoResource;
  if (!resource) {
    showToast("当前没有可核验的视频链接，请稍后重试联网检索");
    return;
  }
  const embedUrl = safeEmbedUrl(resource.embed_url);
  if (!embedUrl) {
    // 该视频源不支持页内内嵌（如 MOOC/学堂在线）：打开页面内详情弹窗，
    // 用户可自行决定是否点击来源链接，页面绝不自动跳转
    openVideoDetail(resource);
    return;
  }
  const frame = document.querySelector("#video-frame");
  document.querySelector("#media-stage").hidden = false;
  frame.src = embedUrl;
  frame.hidden = false;
  document.querySelector("#media-placeholder").hidden = true;
  document.querySelector("#media-stage").classList.add("has-video");
  showToast(`正在播放来自${resource.source || resource.source_domain || "联网来源"}的视频`);
}

async function setQuestion(questionId) {
  document.querySelectorAll("[data-question]").forEach((button) => {
    button.classList.toggle("active", button.dataset.question === questionId);
  });
  if (questionId === "q8") {
    if (state.reviewResumeToken) {
      // 已有未完成的澄清会话：直接继续补充，避免重复创建工作流会话
      document.querySelector("#clarification-dialog .clarification-copy").textContent =
        "请继续补充本题缺失的题目描述或你的作答，系统将恢复本次讲解。";
      document.querySelector("#clarification-input").value = "";
      if (!document.querySelector("#clarification-dialog").open) {
        document.querySelector("#clarification-dialog").showModal();
      }
      return;
    }
    try {
      await requestReview({
        attempt_id: "DEMO-Q8",
        route_type: "error_remediation",
        question_snapshot: { question_id: "Q-008", question_text: "" },
        current_attempt: { student_answer: "average = sum(values) / len(values)" },
        validated_evaluation: {
          validation_passed: true,
          evaluation_status: "incorrect",
          error_points: [{
            error_id: "MISSING_QUESTION_CONTEXT",
            knowledge_point_id: "KN_JAVA_INHERITANCE",
            knowledge_point_name: "继承与方法重写",
          }],
        },
      });
    } catch (error) {
      // The request bridge preserves the previous explanation on failure.
    }
    return;
  }
  const content = reviewContent[questionId];
  const workspace = document.querySelector("#question-workspace");
  const flowTitles = document.querySelectorAll("#explanation-panel .flow-step strong");
  const flowBodies = document.querySelectorAll("#explanation-panel .flow-step p");
  const retryHint = document.querySelector("#explanation-panel .retry-hint p");
  workspace.querySelector("h2").textContent = content.title;
  const meta = workspace.querySelectorAll(".question-meta span");
  meta[0].textContent = content.meta;
  meta[1].textContent = content.knowledge;
  if (questionId === "q6") {
    workspace.querySelector(".dataset-row").innerHTML = `
      <span>有效成绩集合 <strong>[]</strong></span>
      <span>当前行为 <strong class="absent">NullPointerException</strong></span>
    `;
    workspace.querySelector(".student-answer code").textContent = "for (int s : scores) { if (s > 0) total += s; } // scores 含 null 元素";
    workspace.querySelector(".student-answer p").innerHTML = "集合中存在 <mark>null 元素</mark>，拆箱比较时直接抛空指针。";
    workspace.querySelector(".expected-answer code").innerHTML = "if (scores == null || scores.length == 0) {<br>&nbsp;&nbsp;&nbsp;&nbsp;return 0;<br>}";
    document.querySelector("#explanation-panel .explanation-heading h2").textContent = "先处理空集合与 null，再执行聚合";
    flowTitles[0].textContent = "先识别边界状态";
    flowBodies[0].textContent = "有效成绩集合为空或含 null 时，平均分暂时没有可计算的数据。";
    flowTitles[1].textContent = "阻止空指针与除零";
    flowBodies[1].textContent = "在遍历和除法之前先判空，并对 null 元素做过滤。";
    flowTitles[2].textContent = "按任务规则返回";
    flowBodies[2].textContent = "返回 0、抛出受控异常或提示信息，不能直接访问 null 元素。";
    retryHint.textContent = "在 averageScore() 入口先检查集合状态，再执行统计。";
  } else {
    workspace.querySelector(".dataset-row").innerHTML = `
      <span>张明 <strong>90</strong></span>
      <span>李华 <strong class="absent">null</strong></span>
      <span>王芳 <strong>60</strong></span>
    `;
    workspace.querySelector(".student-answer code").textContent = "public double averageScore() { return total / scores.length; }";
    workspace.querySelector(".student-answer p").innerHTML = "<mark>直接访问 scores 数组</mark>，绕过了封装，且 null 缺考记录被计入长度。";
    workspace.querySelector(".expected-answer code").innerHTML = "private double[] scores;<br>public List&lt;Double&gt; getValidScores() { ... }";
    document.querySelector("#explanation-panel .explanation-heading h2").textContent = "问题在封装与统计口径，不在加法";
    flowTitles[0].textContent = "先通过封装方法取数";
    flowBodies[0].textContent = "成绩数组保持 private，外部只能通过 getter 获取有效成绩。";
    flowTitles[1].textContent = "总和与数量来自同一集合";
    flowBodies[1].textContent = "先过滤 null 得到有效成绩，总和 150、数量 2。";
    flowTitles[2].textContent = "再进行平均值计算";
    flowBodies[2].innerHTML = "<code>150 / 2 = 75</code>，而不是除以学生总人数 3。";
    retryHint.textContent = "先写出有效成绩集合，再分别从它计算总和与数量。";
  }
}

function currentStageCheck() {
  return stageChecks[state.currentKnowledgePointId] || defaultStageCheck;
}

function renderStageCheck(check) {
  document.querySelector("#check-title").textContent = check.title;
  document.querySelector("#check-prompt").textContent = check.prompt;
  const options = document.querySelector("#check-options");
  options.replaceChildren();
  check.options.forEach(([value, label, text]) => {
    const option = createElement("label", "check-option");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "answer";
    input.value = value;
    option.append(input, createElement("span", "", label), createElement("code", "", text));
    options.append(option);
  });
}

function openCheck() {
  const dialog = document.querySelector("#check-dialog");
  renderStageCheck(currentStageCheck());
  document.querySelector("#check-feedback").hidden = true;
  document.querySelectorAll('input[name="answer"]').forEach((input) => {
    input.checked = false;
  });
  dialog.showModal();
}

async function submitCheck(control) {
  const selected = document.querySelector('input[name="answer"]:checked');
  const feedback = document.querySelector("#check-feedback");
  feedback.hidden = false;
  if (!selected) {
    feedback.className = "check-feedback incorrect";
    feedback.textContent = "请先选择一个计算式。";
    return;
  }
  const check = currentStageCheck();
  setControlPending(control, true);
  feedback.className = "check-feedback";
  feedback.textContent = "正在核验答案并更新学习路径。";
  try {
    const result = await requestLearning(WORKFLOW_EVENTS.checkFeedback, {
      selected_answer: selected.value,
      feedback: check.incorrectFeedback,
      question_id: `CHECK-${state.currentKnowledgePointId}`,
      question_text: check.prompt,
      options: Object.fromEntries(check.options.map(([key]) => [key, key])),
    }, false);
    // 通过与否由服务端判定（客户端不再自行判题，防止伪造 passed）
    const passed = result.check_feedback?.passed === true;
    if (result.status !== WORKFLOW_STATUSES.ok) {
      feedback.className = "check-feedback incorrect";
      feedback.textContent = result.user_message || "学习路径暂未更新，请稍后重试。";
      return;
    }
    if (passed && !hasRenderableLearningOutcome(result)) {
      feedback.className = "check-feedback incorrect";
      feedback.textContent = learningOutcomeUnavailable(result);
      return;
    }
    applyWorkflowResult(result);
    document.querySelector("#check-dialog").close();
    if (passed) {
      showToast(result.path_update?.next_knowledge_point_id
        ? "答案正确，已进入下一节学习。"
        : "答案正确，当前学习节点已完成。");
      return;
    }
    // 答错 → 生成纠错讲解并进入测验讲解页（阶段检查闭环）
    const correctText = check.options.find(([key]) => key === check.correctAnswer)?.[2] || check.correctAnswer;
    try {
      const correction = await window.workflowBackend.explain({
        scene: "error_correction",
        question_snapshot: {
          question_id: `CHECK-${state.currentKnowledgePointId}`,
          question_text: check.prompt,
        },
        current_attempt: { student_answer: selected.value },
        validated_evaluation: {
          validation_passed: true,
          evaluation_status: "incorrect",
          score: 0,
          max_score: 1,
          error_points: [{
            error_id: "STAGE_CHECK_INCORRECT",
            knowledge_point_id: state.currentKnowledgePointId,
            knowledge_point_name: state.currentKnowledgePointTitle || "当前知识点",
            error_type: "practice",
            student_evidence: selected.value,
            expected_behavior: correctText,
            diagnosis: "阶段检查未通过，需要针对性讲解",
            root_cause: "关键规则尚未稳定掌握",
            severity: "medium",
            confidence: 1.0,
          }],
        },
      }, false);
      if (correction.status === WORKFLOW_STATUSES.ok) {
        applyWorkflowResult(correction);
        setPage("review");
        showToast("已根据本次作答生成纠错讲解");
      } else {
        feedback.textContent = correction.user_message || "已记录答案，但纠错讲解暂未生成。";
      }
    } catch (error) {
      feedback.textContent = "已记录答案，纠错讲解生成失败，请稍后重试。";
    }
  } catch (error) {
    feedback.className = "check-feedback incorrect";
    feedback.textContent = error instanceof Error
      ? `提交失败：${error.message}`
      : "提交失败，当前答案仍可再次提交。";
  } finally {
    setControlPending(control, false);
  }
}

async function handleClarification(control) {
  const value = document.querySelector("#clarification-input").value.trim();
  if (!value) {
    showToast("请先填写题目或任务描述");
    return;
  }
  setControlPending(control, true);
  try {
    const result = await requestReview({
      resume_token: state.reviewResumeToken,
      clarification_reply: value,
    });
    if (result.status === WORKFLOW_STATUSES.ok) {
      document.querySelector("#clarification-dialog").close();
      showToast("已补充信息并恢复测验讲解。");
    }
  } catch (error) {
    // Keep the clarification dialog open so the learner can retry.
  } finally {
    setControlPending(control, false);
  }
}

async function endClarification(control) {
  setControlPending(control, true);
  try {
    const result = await requestReview({
      resume_token: state.reviewResumeToken,
      clarification_reply: "无法提供，结束本次工作流",
    });
    if (result.status === WORKFLOW_STATUSES.endedByUser) {
      showToast("本次测验讲解已结束。");
    }
  } catch (error) {
    // The request bridge has already shown the failure.
  } finally {
    setControlPending(control, false);
  }
}

function closeTopbarPanels(exceptId = "") {
  for (const panelId of ["notifications-panel", "profile-panel"]) {
    if (panelId === exceptId) continue;
    document.querySelector(`#${panelId}`).hidden = true;
  }
  document.querySelector("#notifications-button").setAttribute(
    "aria-expanded",
    String(exceptId === "notifications-panel" && !document.querySelector("#notifications-panel").hidden),
  );
  document.querySelector("#profile-button").setAttribute(
    "aria-expanded",
    String(exceptId === "profile-panel" && !document.querySelector("#profile-panel").hidden),
  );
}

function renderNotifications(result) {
  const items = Array.isArray(result?.items) ? result.items : [];
  const list = document.querySelector("#notification-list");
  list.replaceChildren();
  if (!items.length) list.append(createElement("p", "empty-state", "暂无通知"));
  items.forEach((item) => {
    const button = createElement("button", `notification-item ${item.read_at ? "" : "unread"}`);
    button.type = "button";
    button.append(
      createElement("strong", "", item.title || "学习通知"),
      createElement("span", "", item.message || ""),
    );
    button.addEventListener("click", async () => {
      if (!item.read_at) {
        try {
          await window.workflowBackend.markNotificationRead(item.notification_id);
          button.classList.remove("unread");
          item.read_at = new Date().toISOString();
          const remaining = items.filter((entry) => !entry.read_at).length;
          updateNotificationCount(remaining);
        } catch (error) {
          // 保持未读状态并提示，避免本地计数与后端不一致
          showToast("通知状态更新失败，请稍后重试。");
        }
      }
    });
    list.append(button);
  });
  updateNotificationCount(Number(result?.unread_count) || 0);
}

function updateNotificationCount(count) {
  document.querySelector("#notification-count").textContent = `${count} 条未读`;
  document.querySelector("#notification-dot").hidden = count === 0;
}

async function toggleNotifications() {
  const panel = document.querySelector("#notifications-panel");
  const opening = panel.hidden;
  closeTopbarPanels(opening ? "notifications-panel" : "");
  panel.hidden = !opening;
  document.querySelector("#notifications-button").setAttribute("aria-expanded", String(opening));
  if (opening) {
    try {
      renderNotifications(await window.workflowBackend.getNotifications());
    } catch (error) {
      panel.hidden = true;
      // 失败时恢复 aria-expanded，避免与面板状态错位
      document.querySelector("#notifications-button").setAttribute("aria-expanded", "false");
    }
  }
}

function toggleProfile() {
  const panel = document.querySelector("#profile-panel");
  const opening = panel.hidden;
  closeTopbarPanels(opening ? "profile-panel" : "");
  panel.hidden = !opening;
  document.querySelector("#profile-button").setAttribute("aria-expanded", String(opening));
}

function applySettings(settings = {}) {
  state.settings = settings;
  const deliveryMode = settings.preferred_delivery_mode === "video" ? "video" : "text";
  document.querySelector("#preferred-delivery-mode").value = deliveryMode;
  document.querySelector("#explanation-depth").value = settings.explanation_depth || "guided";
  document.querySelector("#reduced-motion").checked = Boolean(settings.reduced_motion);
  document.querySelector("#auto-play-video").checked = Boolean(settings.auto_play_video);
  document.body.classList.toggle("reduced-motion", Boolean(settings.reduced_motion));
}

function renderWeaknessBreakdown(learningPath) {
  const container = document.querySelector("#weakness-breakdown");
  if (!container) return;
  container.replaceChildren();
  const items = Array.isArray(learningPath?.items) ? learningPath.items : [];
  const rows = items
    .filter((item) => item && item.knowledge_point_name && Number.isFinite(Number(item.mastery)))
    .map((item) => ({ item, mastery: Number(item.mastery) }))
    .sort((a, b) => a.mastery - b.mastery)
    .slice(0, 3);
  if (!rows.length) {
    container.append(createElement("p", "empty-state", "暂无掌握度数据，完成学习后自动生成"));
    return;
  }
  rows.forEach(({ item, mastery }) => {
    const clamped = Math.max(0, Math.min(100, mastery));
    const nameRow = createElement("div", "");
    nameRow.append(createElement("span", "", item.knowledge_point_name));
    container.append(nameRow);
    const strong = createElement("strong", "", `${clamped}%`);
    container.append(strong);
    const track = createElement("div", `mini-track ${clamped < 60 ? "amber" : ""}`);
    track.append(createElement("span", "", ""));
    track.querySelector("span").style.width = `${clamped}%`;
    container.append(track);
  });
}

function applyBootstrap(detail) {
  const profile = detail?.profile || {};
  state.profile = profile;
  document.querySelector("#profile-display-name").textContent = profile.display_name || "林同学";
  document.querySelector("#profile-student-id").textContent = profile.student_id || window.workflowBackend.studentId;
  document.querySelector("#topbar-student-id").textContent = profile.student_id || window.workflowBackend.studentId;
  document.querySelector("#profile-program-name").textContent = profile.program_name || "Java 面向对象程序设计实训";
  document.querySelector(".profile-name").textContent = profile.display_name || "林同学";
  const avatarText = (profile.display_name || "林").slice(0, 1);
  document.querySelectorAll(".avatar").forEach((avatar) => { avatar.textContent = avatarText; });
  state.favorite = Boolean(detail?.current_favorite);
  updateFavoriteControl();
  updateNotificationCount(Number(detail?.notification_unread_count) || 0);
  applySettings(detail?.settings || {});
  state.learningPath = detail?.learning_path;
  renderWeaknessBreakdown(detail?.learning_path);
}

function updateFavoriteControl() {
  const button = document.querySelector("#favorite-button");
  button.setAttribute("aria-pressed", String(state.favorite));
  button.title = state.favorite ? "取消收藏本节" : "收藏本节";
  button.setAttribute("aria-label", button.title);
  button.classList.toggle("active", state.favorite);
}

async function toggleFavorite(control) {
  const desired = !state.favorite;
  setControlPending(control, true);
  try {
    const result = await window.workflowBackend.setFavorite({
      knowledge_point_id: state.currentKnowledgePointId || "KN_JAVA_ENCAPSULATION",
      title: state.currentKnowledgePointTitle || "当前知识点",
      favorite: desired,
    });
    state.favorite = Boolean(result.favorite);
    updateFavoriteControl();
    showToast(state.favorite ? "已收藏本节" : "已取消收藏");
  } catch (error) {
    // Keep the persisted state shown in the control.
  } finally {
    setControlPending(control, false);
  }
}

function toggleMoreActions() {
  const menu = document.querySelector("#more-menu");
  const trigger = document.querySelector("#more-actions");
  const opening = Boolean(menu && menu.hidden);
  if (menu) menu.hidden = !opening;
  if (trigger) trigger.setAttribute("aria-expanded", String(opening));
}

function toggleLearningPath() {
  state.pathCollapsed = !state.pathCollapsed;
  const grid = document.querySelector(".learning-grid");
  const button = document.querySelector("#path-collapse-button");
  grid.classList.toggle("path-collapsed", state.pathCollapsed);
  button.setAttribute("aria-expanded", String(!state.pathCollapsed));
  button.title = state.pathCollapsed ? "展开学习路径" : "收起学习路径";
  button.setAttribute("aria-label", button.title);
  button.innerHTML = `<i data-lucide="${state.pathCollapsed ? "panel-left-open" : "panel-left-close"}"></i>`;
  lucide.createIcons();
}

function toggleLearningContext() {
  state.contextCollapsed = !state.contextCollapsed;
  const panel = document.querySelector("#context-panel");
  const button = document.querySelector("#context-collapse-button");
  panel.classList.toggle("context-collapsed", state.contextCollapsed);
  button.setAttribute("aria-expanded", String(!state.contextCollapsed));
  button.title = state.contextCollapsed ? "展开策略面板" : "收起策略面板";
  button.setAttribute("aria-label", button.title);
  button.innerHTML = `<i data-lucide="${state.contextCollapsed ? "panel-right-open" : "panel-right-close"}"></i>`;
  lucide.createIcons();
}

async function selectPathNode(button) {
  if (button.disabled) return;
  if (button.getAttribute("aria-current") === "step") {
    showToast("当前已在该学习节点");
    return;
  }
  setControlPending(button, true);
  try {
    await window.workflowBackend.explain({
      scene: "learn",
      event_type: WORKFLOW_EVENTS.initializeLearning,
      current_knowledge_point: {
        knowledge_point_id: button.dataset.knowledgePointId,
        knowledge_point_name: button.dataset.knowledgePointName,
        knowledge_type: button.dataset.knowledgeType,
        mastery: Number(button.dataset.mastery) || 0,
      },
    });
    showToast(`已打开${button.dataset.knowledgePointName}`);
  } catch (error) {
    // The current lesson stays in place.
  } finally {
    setControlPending(button, false);
  }
}

const SOURCE_TYPE_LABELS = {
  document: "教材/文档",
  web: "联网检索",
  video: "视频",
  diagnosis: "诊断",
  kb: "知识库",
  standard: "标准/规范",
  resource: "学习资源",
  textbook: "教材",
  interactive_document: "互动文档",
  practice: "练习",
};

const VERIFICATION_LABELS = {
  verified: "已核验",
  provided: "已提供",
  whitelisted: "白名单",
  web_sourced: "联网检索",
};

function renderSources(items) {
  const list = document.querySelector("#source-reference-list");
  list.replaceChildren();
  if (!items.length) {
    list.append(createElement("p", "empty-state", "当前讲解没有可展示的来源记录"));
    return;
  }
  items.forEach((source) => {
    const item = createElement("article", "source-reference-item");
    const heading = createElement("header");
    const typeLabel = SOURCE_TYPE_LABELS[source.source_type] || source.source_type || "资料";
    const verifyLabel = VERIFICATION_LABELS[source.verification_state] || source.verification_state || "已提供";
    heading.append(
      createElement("span", `source-type source-type-${source.source_type || "document"}`, typeLabel),
      createElement("strong", "", source.title || "讲解来源"),
      createElement("span", "source-verify", verifyLabel),
    );
    item.append(heading);
    if (source.document_id || source.locator) {
      item.append(createElement("small", "", [source.document_id, source.locator].filter(Boolean).join(" · ")));
    }
    if (source.quote_text) item.append(createElement("p", "", source.quote_text));
    const url = safeHttpUrl(source.url);
    if (url) {
      const link = createElement("a", "", "打开原始资料");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.append(link);
    }
    list.append(item);
  });
}

async function openSources(kind, control) {
  const sessionId = kind === "review" ? state.reviewExplanationSessionId : state.learningExplanationSessionId;
  let items = kind === "review" ? state.reviewSources : state.learningSources;
  setControlPending(control, true);
  try {
    if (!items.length && sessionId) {
      const result = await window.workflowBackend.getSources(sessionId);
      items = Array.isArray(result.items) ? result.items : [];
    }
    renderSources(items);
    document.querySelector("#sources-dialog").showModal();
  } catch (error) {
    showToast("当前讲解暂时没有来源记录");
  } finally {
    setControlPending(control, false);
  }
}

function renderGrowthChart(attempts) {
  const container = document.querySelector("#growth-chart");
  if (!container) return;
  const empty = document.querySelector("#growth-empty");
  const ordered = [...attempts].reverse();
  if (ordered.length < 2) {
    container.replaceChildren();
    if (empty) {
      empty.hidden = false;
      container.append(empty);
    } else {
      container.append(createElement("p", "empty-state", "至少完成 2 次练习后生成成长曲线"));
    }
    return;
  }
  if (empty) empty.hidden = true;
  container.replaceChildren();
  const width = 560;
  const height = 180;
  const pad = { l: 38, r: 12, t: 16, b: 26 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  let correct = 0;
  const points = ordered.map((item, index) => {
    if (String(item.status).toLowerCase() === "correct") correct += 1;
    const rate = correct / (index + 1);
    return {
      x: pad.l + (index / Math.max(1, ordered.length - 1)) * innerW,
      y: pad.t + (1 - rate) * innerH,
      rate,
      label: item.created_at
        ? new Date(item.created_at).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })
        : "",
    };
  });
  const svg = createElement("svg", "growth-svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "练习正确率成长曲线");
  let markup = "";
  for (let grid = 0; grid <= 4; grid += 1) {
    const y = pad.t + (grid / 4) * innerH;
    markup += `<line x1="${pad.l}" y1="${y}" x2="${width - pad.r}" y2="${y}" stroke="var(--line)" stroke-width="1"/>`;
    markup += `<text x="${pad.l - 6}" y="${y + 4}" text-anchor="end" class="chart-axis">${100 - grid * 25}%</text>`;
  }
  const path = points.map((pt, index) => `${index ? "L" : "M"}${pt.x},${pt.y}`).join(" ");
  markup += `<path d="${path}" fill="none" stroke="var(--green)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`;
  const labelStep = Math.max(1, Math.ceil(points.length / 6));
  points.forEach((pt, index) => {
    markup += `<circle cx="${pt.x}" cy="${pt.y}" r="4" fill="var(--green)"/>`;
    if (index % labelStep === 0 || index === points.length - 1) {
      markup += `<text x="${pt.x}" y="${height - 6}" text-anchor="middle" class="chart-axis">${pt.label || ""}</text>`;
    }
    markup += `<text x="${pt.x}" y="${pt.y - 8}" text-anchor="middle" class="chart-value">${Math.round(pt.rate * 100)}%</text>`;
  });
  svg.innerHTML = markup;
  container.append(svg);
  const latest = points[points.length - 1];
  container.append(
    createElement(
      "p",
      "chart-summary",
      `累计 ${ordered.length} 次练习，当前正确率 ${Math.round(latest.rate * 100)}%`,
    ),
  );
}

// ---------- 诊断页（目标 → 测评 → 归因薄弱点）----------

function splitKnowledgeLabel(label) {
  const text = String(label || "").trim();
  if (!text) return [text];
  if (text.length <= 6) return [text];
  const separators = ["与", "和", "及", "、"];
  const positions = separators
    .map((sep) => text.indexOf(sep))
    .filter((index) => index > 0 && index < 6);
  if (positions.length) {
    const cut = Math.min(...positions) + 1;
    return [text.slice(0, cut), ...splitKnowledgeLabel(text.slice(cut))].slice(0, 3);
  }
  return (text.match(/.{1,6}/g) || [text]).slice(0, 3);
}

function renderDiagnosisPrompt() {
  document.querySelector("#diagnosis-q-index").textContent = "--";
  document.querySelector("#diagnosis-q-total").textContent = state.diagnosisTotal || "--";
  document.querySelector(".diagnosis-question-meta").hidden = true;
  const codeBlock = document.querySelector(".diagnosis-code-preview");
  if (codeBlock) codeBlock.hidden = true;
  document.querySelector(".diagnosis-question h2").textContent =
    "请选择左侧学习目标，然后点击「提交并下一题」开始本轮诊断（约 6-8 道选择题）。";
  document.querySelector(".diagnosis-options").replaceChildren();
  const feedback = document.querySelector("#diagnosis-feedback");
  if (feedback) feedback.hidden = true;
  const summary = document.querySelector("#diagnosis-summary");
  if (summary) summary.hidden = true;
}

function renderDiagnosisQuestion(question) {
  document.querySelector("#diagnosis-q-index").textContent = state.diagnosisIndex + 1;
  document.querySelector("#diagnosis-q-total").textContent = state.diagnosisTotal;
  const meta = document.querySelector(".diagnosis-question-meta");
  meta.hidden = false;
  meta.querySelector(".topic-code").textContent = question.knowledge_point_id || "";
  meta.querySelector(".diagnosis-tag").textContent = question.knowledge_point_name || "";
  const codeBlock = document.querySelector(".diagnosis-code-preview");
  if (codeBlock) codeBlock.hidden = true;
  document.querySelector(".diagnosis-question h2").textContent = question.title || "";
  const optionsBox = document.querySelector(".diagnosis-options");
  optionsBox.replaceChildren();
  ["a", "b", "c", "d"].forEach((key) => {
    const text = question.options?.[key];
    if (!text) return;
    const label = document.createElement("label");
    label.className = "check-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "diagnosis-answer";
    input.value = key;
    label.append(input, createElement("span", "", key.toUpperCase()));
    const body = createElement("span", "", String(text));
    label.append(body);
    optionsBox.append(label);
  });
  const feedback = document.querySelector("#diagnosis-feedback");
  if (feedback) feedback.hidden = true;
  const summary = document.querySelector("#diagnosis-summary");
  if (summary) summary.hidden = true;
  document.querySelector("#diagnosis-submit").disabled = false;
  document.querySelector("#diagnosis-skip").disabled = false;
}

function renderDiagnosisFeedback(result) {
  const feedback = document.querySelector("#diagnosis-feedback");
  feedback.hidden = false;
  const icon = feedback.querySelector(".feedback-icon");
  icon.className = `feedback-icon ${result.correct ? "correct" : "incorrect"}`;
  icon.innerHTML = result.correct
    ? '<i data-lucide="check"></i>'
    : '<i data-lucide="x"></i>';
  feedback.querySelector("strong").textContent = result.correct ? "回答正确" : "回答错误";
  feedback.querySelector("p").textContent =
    result.explanation || (result.correct ? "掌握情况良好。" : "可回到学习页复习该知识点。");
  const meta = feedback.querySelector(".feedback-meta");
  if (meta) meta.textContent = `${result.knowledge_point_name || ""} · 已归因`;
  if (window.lucide) window.lucide.createIcons();
}

function renderDiagnosisSummary() {
  const summary = document.querySelector("#diagnosis-summary");
  if (!summary || !state.diagnosisSummary) return;
  summary.hidden = false;
  summary.querySelector(".summary-copy").textContent = state.diagnosisSummary.feedback || "诊断完成。";
  const chips = summary.querySelector(".summary-chips");
  chips.replaceChildren();
  (state.diagnosisSummary.weak_points || []).forEach((point) => {
    chips.append(
      createElement(
        "span",
        "summary-chip",
        `${point.knowledge_point_name}（答错 ${point.error_count} 题）`,
      ),
    );
  });
  if (window.lucide) window.lucide.createIcons();
  // 完成态：隐藏答题按钮，改为「去学习薄弱点」引导
  document.querySelector("#diagnosis-submit").hidden = true;
  document.querySelector("#diagnosis-skip").hidden = true;
  const finish = document.querySelector("#diagnosis-finish");
  if (finish) finish.hidden = false;
  // 刷新覆盖图：诊断已更新后端掌握度
  window.workflowBackend.bootstrap().then((detail) => {
    state.learningPath = detail?.learning_path;
    renderDiagnosisCoverage(state.learningPath);
  }).catch(() => {});
}

function renderDiagnosisStats() {
  const stats = state.diagnosisStats || {};
  const done = Boolean(stats.done);
  const answered = (stats.correct || 0) + (stats.wrong || 0) + (stats.skipped || 0);
  const total = state.diagnosisTotal || 0;
  const percent = total ? Math.round((answered / total) * 100) : 0;
  const offset = 263.9 * (1 - percent / 100);
  const ring = document.querySelector(".round-ring");
  if (ring) {
    ring.querySelector("circle:last-of-type").setAttribute("stroke-dashoffset", String(offset));
    ring.querySelector("text:first-of-type").textContent = `${percent}%`;
    ring.querySelector("text:last-of-type").textContent = `${answered}/${total}`;
  }
  const labels = { correct: "已答对", wrong: "已答错", skipped: "已跳过" };
  document.querySelectorAll(".round-stat").forEach((statEl) => {
    const key = Object.keys(labels).find((k) => statEl.querySelector("span")?.textContent === labels[k]);
    if (key) statEl.querySelector("strong").textContent = String(stats[key] || 0);
  });
  document.querySelector("#diagnosis-round-label").textContent = state.diagnosisRound
    ? `第 ${state.diagnosisRound} 轮`
    : "未开始";
}

function renderDiagnosisCoverage(learningPath) {
  const heatmap = document.querySelector("#coverage-heatmap");
  if (!heatmap) return;
  const items = Array.isArray(learningPath?.items) ? learningPath.items : [];
  if (!items.length) return;
  heatmap.replaceChildren();
  items.slice(0, 9).forEach((item) => {
    const mastery = Number(item.mastery) || 0;
    const stateClass =
      mastery >= 80 ? "mastered" : mastery >= 50 ? "partial" : mastery < 40 ? "weak" : "untested";
    const cell = document.createElement("div");
    cell.className = `coverage-cell ${stateClass}`;
    cell.style.setProperty("--cell-label", `'${(item.knowledge_point_name || "").slice(0, 4)}'`);
    cell.title = `${item.knowledge_point_name} · 掌握度 ${mastery}%`;
    cell.append(document.createTextNode((item.knowledge_point_name || "").slice(0, 4)));
    heatmap.append(cell);
  });
}

function loadDiagnosis() {
  renderDiagnosisCoverage(state.learningPath);
  if (state.diagnosisQuestions.length && !state.diagnosisStats.done) {
    renderDiagnosisQuestion(state.diagnosisQuestions[state.diagnosisIndex] || state.diagnosisQuestions[0]);
  } else if (state.diagnosisStats.done) {
    renderDiagnosisSummary();
  } else {
    renderDiagnosisPrompt();
  }
  renderDiagnosisStats();
}

async function handleDiagnosisSubmit() {
  const submitBtn = document.querySelector("#diagnosis-submit");
  submitBtn.disabled = true;
  try {
    if (!state.diagnosisQuestions.length || state.diagnosisStats.done) {
      const result = await window.workflowBackend.startDiagnosis(state.diagnosisGoal);
      state.diagnosisQuestions = result.questions || [];
      state.diagnosisTotal = result.total || state.diagnosisQuestions.length;
      state.diagnosisRound = result.round || 1;
      state.diagnosisStats = { correct: 0, wrong: 0, skipped: 0, done: false };
      state.diagnosisIndex = 0;
      if (state.diagnosisQuestions.length) {
        renderDiagnosisQuestion(state.diagnosisQuestions[0]);
      } else {
        renderDiagnosisPrompt();
      }
      renderDiagnosisStats();
      return;
    }
    const selected = document.querySelector('input[name="diagnosis-answer"]:checked');
    if (!selected) {
      showToast("请先选择一个选项");
      submitBtn.disabled = false;
      return;
    }
    const result = await window.workflowBackend.submitDiagnosisAnswer({ selected: selected.value });
    state.diagnosisStats = result.stats || state.diagnosisStats;
    state.diagnosisIndex = result.stats?.question_index || state.diagnosisIndex + 1;
    if (result.status === "completed") {
      state.diagnosisStats.done = true;
      state.diagnosisSummary = result.summary;
      renderDiagnosisFeedback(result);
      renderDiagnosisSummary();
      renderDiagnosisStats();
      return;
    }
    renderDiagnosisFeedback(result);
    if (state.diagnosisQuestions[state.diagnosisIndex]) {
      renderDiagnosisQuestion(state.diagnosisQuestions[state.diagnosisIndex]);
    }
    renderDiagnosisStats();
  } catch (error) {
    showToast(`诊断请求失败：${error.message || "请稍后重试"}`);
  } finally {
    submitBtn.disabled = false;
  }
}

async function handleDiagnosisSkip() {
  try {
    if (!state.diagnosisQuestions.length) {
      showToast("请先开始诊断");
      return;
    }
    const result = await window.workflowBackend.submitDiagnosisAnswer({ skipped: true });
    state.diagnosisStats = result.stats || state.diagnosisStats;
    state.diagnosisIndex = result.stats?.question_index || state.diagnosisIndex + 1;
    if (result.status === "completed") {
      state.diagnosisStats.done = true;
      state.diagnosisSummary = result.summary;
      renderDiagnosisSummary();
      renderDiagnosisStats();
      return;
    }
    if (state.diagnosisQuestions[state.diagnosisIndex]) {
      renderDiagnosisQuestion(state.diagnosisQuestions[state.diagnosisIndex]);
    }
    renderDiagnosisStats();
  } catch (error) {
    showToast(`诊断请求失败：${error.message || "请稍后重试"}`);
  }
}

function renderRecords(result) {  const explanations = Array.isArray(result?.explanations) ? result.explanations : [];
  const attempts = Array.isArray(result?.attempts) ? result.attempts : [];
  const explanationList = document.querySelector("#explanation-record-list");
  const attemptList = document.querySelector("#attempt-record-list");
  explanationList.replaceChildren();
  attemptList.replaceChildren();
  const explanationTypeLabels = {
    concept_guidance: "概念引导",
    worked_example: "示例讲解",
    execution_trace: "执行轨迹",
    video_interactive: "视频互动",
    interactive_document: "互动图文",
    step_breakdown: "分步骤讲解",
    alternative: "换种讲法",
    targeted_explanation: "针对性讲解",
    error_analysis: "错误归因",
    step_by_step: "分步讲解",
    example_driven: "案例讲解",
    evidence_contrast: "证据对比",
  };
  const deliveryLabels = {
    interactive_document: "互动图文",
    video_interactive: "视频互动",
    video: "视频教学",
    text: "图文",
    execution_trace: "执行轨迹",
    worked_example: "示例讲解",
  };
  explanations.forEach((item) => {
    const row = createElement("article", "record-item");
    row.append(
      createElement("strong", "", item.scene === "learn" ? "学习讲解" : item.scene === "re_explain" ? "换种讲法" : "错题讲解"),
      createElement("span", "", `${explanationTypeLabels[item.explanation_type] || item.explanation_type || "个性化讲解"} · ${deliveryLabels[item.delivery_mode] || item.delivery_mode || "图文"}`),
      createElement("time", "", new Date(item.created_at).toLocaleString("zh-CN")),
    );
    explanationList.append(row);
  });
  attempts.forEach((item) => {
    const row = createElement("article", "record-item");
    row.append(
      createElement("strong", "", item.title || "练习作答"),
      createElement("span", "", item.status === "correct" ? "回答正确" : "需要继续纠正"),
      createElement("time", "", new Date(item.created_at).toLocaleString("zh-CN")),
    );
    attemptList.append(row);
  });
  if (!explanations.length) explanationList.append(createElement("p", "empty-state", "暂无讲解记录"));
  if (!attempts.length) attemptList.append(createElement("p", "empty-state", "暂无练习记录"));
  document.querySelector("#explanation-record-count").textContent = `${explanations.length} 条`;
  document.querySelector("#attempt-record-count").textContent = `${attempts.length} 条`;
  renderGrowthChart(attempts);
}

async function loadGrowth() {
  const page = document.querySelector("#growth-page");
  if (!page) return;
  try {
    const data = await window.workflowBackend.getGrowth();
    const kpi = (data && data.kpi) || {};
    // KPI 条（替换静态 42/87%/12/3）
    const kpiNodes = page.querySelectorAll(".growth-kpi strong");
    const kpiValues = [kpi.nodes_total ?? 0, `${kpi.avg_mastery ?? 0}%`, kpi.badges_earned ?? 0, kpi.diagnosis_rounds ?? 0];
    kpiNodes.forEach((node, index) => { node.textContent = String(kpiValues[index] ?? 0); });
    // 徽章墙（替换静态徽章列表）
    const badges = Array.isArray(data && data.badges) ? data.badges : [];
    const earnedCount = badges.filter((badge) => badge.earned).length;
    const badgeHeader = page.querySelector(".growth-card-heading h2");
    if (badgeHeader) badgeHeader.textContent = `已解锁 ${earnedCount} / ${badges.length} 枚`;
    const progressSmall = page.querySelector(".growth-badge-progress small");
    const progressBar = page.querySelector(".growth-badge-progress .mini-track span");
    if (badges.length) {
      const pct = Math.round((earnedCount / badges.length) * 100);
      if (progressSmall) progressSmall.textContent = `${pct}%`;
      if (progressBar) progressBar.style.width = `${pct}%`;
    }
    const badgeGrid = page.querySelector(".badge-grid");
    if (badgeGrid && badges.length) {
      badgeGrid.replaceChildren(...badges.map((badge) => {
        const item = createElement("div", `badge-item ${badge.earned ? "earned" : "locked"}`);
        const body = createElement("div", "");
        body.append(createElement("strong", "", badge.title), createElement("small", "", badge.desc));
        item.append(createElement("span", "badge-icon", ""), body);
        item.querySelector(".badge-icon").innerHTML = badge.earned
          ? '<i data-lucide="check-circle-2"></i>'
          : '<i data-lucide="lock-keyhole"></i>';
        return item;
      }));
    }
    // 能力对比（诊断前后变化，真实作答正确率）
    const compare = (data && data.ability_comparison) || {};
    const abilityBars = page.querySelectorAll(".ability-bar");
    if (abilityBars.length >= 2) {
      const before = abilityBars[0];
      const after = abilityBars[1];
      before.style.width = `${compare.early_rate ?? 0}%`;
      before.querySelector(".ability-val").textContent = `${compare.early_rate ?? 0}%`;
      after.style.width = `${compare.late_rate ?? 0}%`;
      after.querySelector(".ability-val").textContent = `${compare.late_rate ?? 0}%`;
    }
    // 时间线（最近作答）
    const timeline = Array.isArray(data && data.timeline) ? data.timeline : [];
    const timelineEl = page.querySelector(".growth-timeline, #growth-timeline");
    if (timelineEl && timeline.length) {
      timelineEl.replaceChildren(...timeline.slice(0, 8).map((entry) => {
        const row = createElement("div", "timeline-item");
        row.append(
          createElement("strong", "", entry.title || "练习作答"),
          createElement("span", "", entry.status === "correct" ? "✓ 正确" : "✗ 待复习"),
        );
        return row;
      }));
    }
    if (window.lucide) window.lucide.createIcons();
  } catch (error) {
    // 数据加载失败时保留空态，不显示假数据
    const empty = page.querySelector(".growth-empty");
    if (empty) empty.hidden = false;
  }
}

async function loadRecords() {  try {
    renderRecords(await window.workflowBackend.getRecords());
  } catch (error) {
    // The request bridge displays the error and keeps existing records visible.
  }
}

async function loadSettings() {
  try {
    const result = await window.workflowBackend.getSettings();
    applySettings(result.settings || {});
  } catch (error) {
    // Keep the last known values.
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const button = document.querySelector("#save-settings");
  setControlPending(button, true);
  try {
    const result = await window.workflowBackend.saveSettings({
      preferred_delivery_mode: document.querySelector("#preferred-delivery-mode").value,
      explanation_depth: document.querySelector("#explanation-depth").value,
      reduced_motion: document.querySelector("#reduced-motion").checked,
      auto_play_video: document.querySelector("#auto-play-video").checked,
    });
    applySettings(result.settings || {});
    showToast("设置已保存");
  } catch (error) {
    // Keep the form available for retry.
  } finally {
    setControlPending(button, false);
  }
}

function applyQuestionFilter() {
  const selected = new Set(
    Array.from(document.querySelectorAll('input[name="question-status"]:checked')).map((input) => input.value),
  );
  document.querySelectorAll("[data-question]").forEach((button) => {
    button.hidden = !selected.has(button.dataset.questionStatus || "incorrect");
  });
  document.querySelector("#question-filter-dialog").close();
  document.querySelector("#question-filter-button").setAttribute("aria-expanded", "false");
  showToast(`已显示 ${document.querySelectorAll("[data-question]:not([hidden])").length} 道题`);
}

async function openPractice(mode, control) {
  setControlPending(control, true);
  try {
    const result = await window.workflowBackend.createPractice({
      mode,
      source_question_instance_id: state.currentQuestionInstanceId,
      task_instance_id: state.currentTaskInstanceId,
      knowledge_point_id: state.currentKnowledgePointId || "KN_JAVA_ENCAPSULATION",
      explanation_session_id: state.reviewExplanationSessionId,
    });
    if (result.status !== WORKFLOW_STATUSES.ok || !result.question) {
      throw new Error(result.user_message || "练习题暂时无法生成，请稍后重试。");
    }
    state.practiceQuestion = result.question;
    const schema = result.question.answer_schema || {};
    document.querySelector("#practice-mode-label").textContent = mode === "retry_original" ? "重做原题" : "同知识点变式题";
    document.querySelector("#practice-title").textContent = result.question.title || "针对性练习";
    document.querySelector("#practice-prompt").textContent = result.question.prompt || "请完成当前题目。";
    document.querySelector("#practice-answer-label").textContent = schema.label || "你的答案";
    const answer = document.querySelector("#practice-answer");
    answer.value = "";
    answer.placeholder = schema.placeholder || "输入答案";
    answer.inputMode = schema.type === "number" ? "decimal" : "text";
    document.querySelector("#practice-feedback").hidden = true;
    document.querySelector("#practice-dialog").showModal();
    answer.focus();
  } catch (error) {
    showToast(error instanceof Error ? error.message : "练习题暂时无法生成，请稍后重试。");
  } finally {
    setControlPending(control, false);
  }
}

async function submitPractice(control) {
  const answer = document.querySelector("#practice-answer").value.trim();
  const feedback = document.querySelector("#practice-feedback");
  if (!answer) {
    feedback.className = "check-feedback incorrect";
    feedback.textContent = "请先填写答案。";
    feedback.hidden = false;
    return;
  }
  setControlPending(control, true);
  try {
    const result = await window.workflowBackend.submitAttempt(
      state.practiceQuestion.question_instance_id,
      answer,
    );
    feedback.className = `check-feedback ${result.correct ? "correct" : "incorrect"}`;
    feedback.textContent = result.feedback;
    feedback.hidden = false;
    state.currentQuestionInstanceId = result.question_instance_id;
    state.currentAttemptId = result.attempt_id;
    if (!result.correct) {
      const correction = await window.workflowBackend.explain({
        scene: "error_correction",
        ...result.explanation_input,
      }, false);
      if (correction.status === WORKFLOW_STATUSES.needsClarification) {
        // 先渲染澄清 dialog（applyWorkflowResult 会 showModal），再关闭练习弹窗
        // 并切到测验讲解页，避免两个模态叠加；补充完成后 resume 恢复讲解
        applyWorkflowResult(correction);
        document.querySelector("#practice-dialog").close();
        setPage("review");
        return;
      }
      if (correction.status !== WORKFLOW_STATUSES.ok) {
        feedback.textContent = correction.user_message || correction.error_message || "已记录答案，但纠错讲解暂未生成。";
        return;
      }
      applyWorkflowResult(correction);
      document.querySelector("#practice-dialog").close();
      setPage("review");
      showToast("已根据本次作答生成纠错讲解");
    } else {
      const learningResult = result.learning_result;
      if (hasRenderableLearningOutcome(learningResult)) {
        applyWorkflowResult(learningResult);
        document.querySelector("#practice-dialog").close();
        setPage("learning");
        showToast(learningResult.path_update?.next_knowledge_point_id
          ? "答案正确，已进入下一节学习。"
          : "答案正确，当前学习节点已完成。");
      } else {
        feedback.className = "check-feedback incorrect";
        feedback.textContent = learningOutcomeUnavailable(learningResult);
      }
    }
  } catch (error) {
    feedback.className = "check-feedback incorrect";
    feedback.textContent = error instanceof Error
      ? `提交失败：${error.message}`
      : "提交失败，当前答案仍可再次提交。";
    feedback.hidden = false;
  } finally {
    setControlPending(control, false);
  }
}

async function requestLearningReExplanation(control, feedbackType = "") {
  setControlPending(control, true);
  try {
    const result = await window.workflowBackend.explain({
      scene: "re_explain",
      source_explanation_session_id: state.learningExplanationSessionId,
      task_instance_id: state.currentTaskInstanceId,
      previous_mode: state.learningMode,
      feedback_type: feedbackType,
      requested_delivery_mode: state.learningMode,
    });
    if (result.status === WORKFLOW_STATUSES.ok) {
      showToast(feedbackType ? "已根据反馈生成新的讲解" : "已生成另一种讲解方式");
    }
  } catch (error) {
    // Keep the previous lesson visible.
  } finally {
    setControlPending(control, false);
  }
}

function bindEvents() {
  document.querySelectorAll("[data-page-target]").forEach((button) => {
    button.addEventListener("click", () => setPage(button.dataset.pageTarget));
  });
  document.querySelectorAll("[data-learning-mode]").forEach((button) => {
    button.addEventListener("click", () => changeLearningMode(button.dataset.learningMode, button));
  });
  document.querySelectorAll("[data-review-mode]").forEach((button) => {
    button.addEventListener("click", () => requestReviewExplanation({
      requestedMode: button.dataset.reviewMode,
      message: "已按选择生成新的测验讲解",
    }, button));
  });
  document.querySelectorAll("[data-question]").forEach((button) => {
    button.addEventListener("click", () => {
      void setQuestion(button.dataset.question);
    });
  });
  document.querySelector("#play-button").addEventListener("click", playVideo);
  document.querySelector("#media-detail-button")?.addEventListener("click", () => {
    if (state.activeVideoResource) openVideoDetail(state.activeVideoResource);
  });
  document.querySelector("#review-video-detail")?.addEventListener("click", () => {
    if (state.reviewVideoResource) openVideoDetail(state.reviewVideoResource);
  });
  document.querySelector("#start-check").addEventListener("click", openCheck);
  document.querySelector("#submit-check").addEventListener("click", (event) => {
    void submitCheck(event.currentTarget);
  });
  document.querySelector("#show-example").addEventListener("click", async (event) => {
    const control = event.currentTarget;
    setControlPending(control, true);
    try {
      const result = await requestLearning(WORKFLOW_EVENTS.showExample);
      if (result.status === WORKFLOW_STATUSES.ok) {
        showToast("已生成另一组最小案例。");
      }
    } catch (error) {
      // Keep the current lesson visible.
    } finally {
      setControlPending(control, false);
    }
  });
  document.querySelector("#show-steps").addEventListener("click", async (event) => {
    const control = event.currentTarget;
    setControlPending(control, true);
    try {
      const result = await requestLearning(WORKFLOW_EVENTS.showSteps);
      if (result.status === WORKFLOW_STATUSES.ok) {
        showToast("已切换为分步骤讲解。");
      }
    } catch (error) {
      // Keep the current lesson visible.
    } finally {
      setControlPending(control, false);
    }
  });
  document.querySelector("#not-understood").addEventListener("click", (event) => requestLearningReExplanation(event.currentTarget, "not_understood"));
  document.querySelector("#switch-explanation").addEventListener("click", (event) => requestLearningReExplanation(event.currentTarget));
  document.querySelector("#review-switch").addEventListener("click", (event) => requestReviewExplanation({
    requestedMode: state.reviewMode,
    avoidType: "previous",
    message: "已生成不同表征方式的测验讲解",
  }, event.currentTarget));
  document.querySelector("#retry-question").addEventListener("click", (event) => openPractice("retry_original", event.currentTarget));
  document.querySelector("#variant-question").addEventListener("click", (event) => openPractice("variant", event.currentTarget));
  document.querySelector("#learn-topic").addEventListener("click", async (event) => {
    const control = event.currentTarget;
    setControlPending(control, true);
    try {
      const result = await requestLearning(WORKFLOW_EVENTS.initializeLearning, {
        source: "post_test_review",
        target_knowledge_point_id: state.currentKnowledgePointId || "KN_JAVA_ENCAPSULATION",
      });
      if (result.status === WORKFLOW_STATUSES.ok) {
        setPage("learning");
        showToast("薄弱知识点已加入连续学习路径。");
      }
    } catch (error) {
      // Keep the learner on the current review page.
    } finally {
      setControlPending(control, false);
    }
  });
  document.querySelector("#continue-workflow").addEventListener("click", (event) => {
    void handleClarification(event.currentTarget);
  });
  document.querySelector("#end-workflow").addEventListener("click", (event) => {
    void endClarification(event.currentTarget);
  });
  document.querySelector("#notifications-button").addEventListener("click", toggleNotifications);
  document.querySelector("#profile-button").addEventListener("click", () => {
    closeTopbarPanels("");
    setPage("profile");
  });
  document.querySelectorAll("[data-profile-target]").forEach((button) => {
    button.addEventListener("click", () => setPage(button.dataset.profileTarget));
  });
  document.querySelector("#profile-switch-goal")?.addEventListener("click", () => openOnboarding(true));
  document.querySelector("#bank-shuffle")?.addEventListener("click", () => {
    shuffleBankQuestions();
    showToast("已换一批题目");
  });
  document.querySelector("#bank-back")?.addEventListener("click", () => {
    closeBankSheet();
  });
  document.querySelectorAll("[data-bank-cat]").forEach((button) => {
    button.addEventListener("click", () => {
      bankCategory = button.dataset.bankCat || "all";
      document.querySelectorAll("[data-bank-cat]").forEach((item) => {
        const active = item === button;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      if (bankCategory === "wrong") {
        void renderWrongBook();
      } else {
        renderBankSheets();
      }
    });
  });
  document.querySelector("#path-collapse-button").addEventListener("click", toggleLearningPath);
  document.querySelector("#context-collapse-button").addEventListener("click", toggleLearningContext);
  document.querySelector("#more-actions").addEventListener("click", (event) => {
    event.stopPropagation();
    toggleMoreActions();
  });
  document.addEventListener("click", () => {
    const menu = document.querySelector("#more-menu");
    if (menu && !menu.hidden) {
      menu.hidden = true;
      document.querySelector("#more-actions").setAttribute("aria-expanded", "false");
    }
  });
  document.querySelectorAll("[data-records-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.recordsTab;
      document.querySelectorAll("[data-records-tab]").forEach((item) => {
        const active = item === tab;
        item.classList.toggle("active", active);
        item.setAttribute("aria-selected", String(active));
      });
      document.querySelector("#records-pane-explanations").hidden = name !== "explanations";
      document.querySelector("#records-pane-attempts").hidden = name !== "attempts";
      document.querySelector("#records-pane-growth").hidden = name !== "growth";
    });
  });
  document.querySelector("#growth-go-practice")?.addEventListener("click", () => {
    setPage("bank");
  });
  document.querySelector("#path-list").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-lesson]");
    if (button) selectPathNode(button);
  });
  document.querySelector("#favorite-button").addEventListener("click", (event) => toggleFavorite(event.currentTarget));
  document.querySelector("#source-button").addEventListener("click", (event) => openSources("learning", event.currentTarget));
  document.querySelector("#review-source-button").addEventListener("click", (event) => openSources("review", event.currentTarget));
  document.querySelector("#question-filter-button").addEventListener("click", (event) => {
    event.currentTarget.setAttribute("aria-expanded", "true");
    document.querySelector("#question-filter-dialog").showModal();
  });
  document.querySelector("#question-filter-dialog").addEventListener("close", () => {
    document.querySelector("#question-filter-button").setAttribute("aria-expanded", "false");
  });
  document.querySelector("#apply-question-filter").addEventListener("click", applyQuestionFilter);
  document.querySelector("#submit-practice").addEventListener("click", (event) => submitPractice(event.currentTarget));
  document.querySelector("#run-practice-code").addEventListener("click", async () => {
    const code = document.querySelector("#practice-answer").value.trim();
    const output = document.querySelector("#practice-run-output");
    if (!code) {
      output.hidden = false;
      output.textContent = "请先在答案框输入要运行的代码（Java 或 Python）。";
      return;
    }
    try {
      const result = await window.workflowBackend.runCode("java", code);
      output.hidden = false;
      if (result.status === "ok") {
        output.textContent = result.output || "（无输出）";
        output.className = "code-run-output";
      } else {
        output.textContent = `${result.error || "执行失败"}\n${result.output || ""}`.trim();
        output.className = "code-run-output error";
      }
    } catch (error) {
      output.hidden = false;
      output.textContent = `运行请求失败：${error.message || "请稍后重试"}`;
      output.className = "code-run-output error";
    }
  });
  document.querySelector("#refresh-records").addEventListener("click", loadRecords);
  document.querySelector("#settings-form").addEventListener("submit", saveSettings);
  document.addEventListener("click", (event) => {
    const clickedInsideTopbar = event.composedPath().some(
      (element) => element instanceof Element && element.classList.contains("topbar-context"),
    );
    if (!clickedInsideTopbar) closeTopbarPanels();
  });
}

function buildFlowStep(step, index) {
  const row = createElement("div", "flow-step");
  row.append(createElement("span", "", String(index + 1)));
  const copy = createElement("div");
  copy.append(createElement("strong", "", step.title || `讲解步骤 ${index + 1}`));
  copy.append(renderRichTextElement(step.content || ""));
  if (step.evidence) copy.append(createElement("small", "step-evidence", `证据：${step.evidence}`));
  row.append(copy);
  return row;
}

function renderStreamingPlaceholder(kind) {
  const container = kind === "learning"
    ? document.querySelector("#content-blocks")
    : document.querySelector("#explanation-panel .explanation-flow");
  container.replaceChildren();
  const placeholder = createElement("div", "streaming-placeholder");
  placeholder.append(createElement("p", "streaming-status", "正在准备讲解内容…"));
  const skeleton = createElement("div", "content-skeleton");
  for (let i = 0; i < 3; i += 1) {
    const block = createElement("div", "skeleton-block");
    block.append(createElement("div", "skeleton-line w60"));
    block.append(createElement("div", "skeleton-line w100"));
    block.append(createElement("div", "skeleton-line w90"));
    block.append(createElement("div", "skeleton-line w40"));
    skeleton.append(block);
  }
  placeholder.append(skeleton);
  container.append(placeholder);
}

function renderFullResult(kind, fallbackResult) {
  // 整包渲染回退：流被锁跳过 / SSE error / 网络失败时使用
  if (kind === "learning") {
    renderContentBlocks(fallbackResult.content_blocks, fallbackResult.user_message || fallbackResult.resource_gap);
  } else {
    const flow = document.querySelector("#explanation-panel .explanation-flow");
    flow.replaceChildren();
    const steps = Array.isArray(fallbackResult.explanation_steps) && fallbackResult.explanation_steps.length
      ? fallbackResult.explanation_steps
      : [{ title: "针对性讲解", content: fallbackResult.personalized_explanation || "已生成本题讲解。" }];
    steps.slice(0, 4).forEach((step, index) => flow.append(buildFlowStep(step, index)));
  }
}

async function consumeExplanationStream(sessionId, kind, fallbackResult) {
  // 按渲染区（learning/review）隔离流锁：两处讲解流可并行，不再互相吞掉
  state.streamActive = state.streamActive || {};
  state.streamSession = state.streamSession || {};
  if (state.streamActive[kind]) {
    // 同一渲染区已有流在跑（快速连续操作）：本次请求整包渲染，
    // 避免 renderStreamingPlaceholder 清空后内容停留在占位符；
    // 同时失效旧流，防止其后续 section 污染新内容
    state.streamSession[kind] = `full:${sessionId}`;
    renderFullResult(kind, fallbackResult);
    return;
  }
  state.streamActive[kind] = true;
  state.streamSession[kind] = sessionId;
  const container = kind === "learning"
    ? document.querySelector("#content-blocks")
    : document.querySelector("#explanation-panel .explanation-flow");
  let placeholder = container.querySelector(".streaming-placeholder");
  try {
    await window.workflowBackend.streamExplanation(sessionId, {
      onEvent(name, data) {
        if (name === "status") {
          if (placeholder) {
            placeholder.querySelector(".streaming-status").textContent = data.message || "正在生成讲解…";
          }
        } else if (name === "section") {
          if (state.streamSession[kind] !== sessionId) return; // 已被新渲染替换，放弃
          const section = data.section || {};
          if (kind === "learning") {
            const index = Number.isFinite(data.index) ? data.index : container.children.length;
            container.append(buildContentSection(section, index));
          } else {
            const index = Number.isFinite(data.index) ? data.index : container.children.length;
            container.append(buildFlowStep({ title: section.title, content: section.content, evidence: section.evidence }, index));
          }
          if (placeholder && placeholder.parentNode) {
            placeholder.remove();
            placeholder = null;
          }
        } else if (name === "done") {
          if (state.streamSession[kind] !== sessionId) return; // 已被新渲染替换，放弃
          if (placeholder && placeholder.parentNode) placeholder.remove();
        } else if (name === "error") {
          if (state.streamSession[kind] !== sessionId) return; // 已被新渲染替换，放弃
          // 后端以 SSE error 事件返回（如会话不存在），展示提示并回退整包渲染
          if (placeholder && placeholder.parentNode) placeholder.remove();
          showToast(data.message || "讲解流加载失败，已显示完整内容。");
          renderFullResult(kind, fallbackResult);
        }
      },
    });
  } catch (error) {
    // The POST response already contains the full package; fall back to rendering it whole.
    renderFullResult(kind, fallbackResult);
  } finally {
    state.streamActive[kind] = false;
  }
}

function bindSelectionFollowUp() {
  const askButton = document.querySelector("#selection-ask-button");
  document.addEventListener("mouseup", (event) => {
    const selection = window.getSelection();
    const text = selection ? selection.toString().trim() : "";
    const container = event.target && event.target.closest
      ? event.target.closest("#lesson-document, #explanation-panel, #portrait-root")
      : null;
    if (!text || !container) {
      askButton.hidden = true;
      return;
    }
    const range = selection.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    askButton.hidden = false;
    askButton.style.left = `${Math.max(8, rect.left + rect.width / 2 - 48)}px`;
    askButton.style.top = `${Math.max(8, rect.top - 46)}px`;
    state.followUpSelection = text;
  });
  document.addEventListener("scroll", () => {
    askButton.hidden = true;
  }, true);
  askButton.addEventListener("click", () => {
    askButton.hidden = true;
    openFollowUpWorkspace(state.followUpSelection);
  });
  document.querySelector("#follow-up-close").addEventListener("click", () => {
    document.querySelector("#follow-up-workspace").hidden = true;
  });
  document.querySelector("#follow-up-form").addEventListener("submit", (event) => {
    event.preventDefault();
    void submitFollowUp();
  });
}

function openFollowUpWorkspace(selection) {
  const sessionId = state.learningExplanationSessionId || state.reviewExplanationSessionId;
  if (!sessionId) {
    showToast("当前没有可追问的讲解会话，请先生成一次讲解。");
    return;
  }
  state.followUpSessionId = sessionId;
  state.followUpHistory = [];
  document.querySelector("#follow-up-workspace").hidden = false;
  document.querySelector("#follow-up-context").textContent = selection
    ? `选中：${selection.slice(0, 40)}${selection.length > 40 ? "…" : ""}`
    : "基于当前讲解内容追问";
  const messages = document.querySelector("#follow-up-messages");
  messages.replaceChildren();
  if (selection) appendFollowUpMessage("user", { question: `请解释我选中的内容：${selection}` });
  document.querySelector("#follow-up-input").value = "";
  document.querySelector("#follow-up-input").focus();
}

function appendFollowUpMessage(role, content) {
  const messages = document.querySelector("#follow-up-messages");
  const empty = messages.querySelector(".follow-up-empty");
  if (empty) empty.remove();
  const bubble = createElement("div", `follow-up-bubble ${role}`);
  if (role === "user") {
    bubble.textContent = content.question || "";
  } else {
    bubble.append(createElement("strong", "", content.answer_title || "讲解"));
    bubble.append(renderRichTextElement(content.answer || ""));
    const sources = Array.isArray(content.sources) ? content.sources : [];
    if (sources.length) {
      const sourceText = sources
        .map((source) => source.title || source.locator || "")
        .filter(Boolean)
        .join("、")
        .slice(0, 60);
      if (sourceText) bubble.append(createElement("small", "bubble-source", `依据：${sourceText}`));
    }
  }
  messages.append(bubble);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
}

async function submitFollowUp() {
  const input = document.querySelector("#follow-up-input");
  const question = input.value.trim();
  if (!question) {
    showToast("请先输入追问内容");
    return;
  }
  if (!state.followUpSessionId) {
    showToast("当前没有可追问的讲解会话");
    return;
  }
  input.value = "";
  appendFollowUpMessage("user", { question });
  const send = document.querySelector("#follow-up-send");
  send.disabled = true;
  try {
    const result = await window.workflowBackend.askExplanation(state.followUpSessionId, {
      selection: state.followUpSelection || "",
      question,
      history: state.followUpHistory,
    });
    if (result.status === "ok") {
      state.followUpHistory.push({ question });
      appendFollowUpMessage("assistant", { answer: result.answer, sources: result.sources });
      const suggestions = document.querySelector("#follow-up-suggestions");
      const followUps = Array.isArray(result.follow_up_questions) ? result.follow_up_questions : [];
      // 后端未返回建议问题时，提供通用追问入口，保证"2-3 轮追问"可用
      const promptList = followUps.length
        ? followUps
        : ["为什么这里要这样处理？", "能换一个更简单的例子吗？", "这个知识点在岗位任务中怎么用？"];
      suggestions.hidden = false;
      suggestions.replaceChildren(
        createElement("span", "suggest-label", result.clarification ? "您想问的是？" : "继续追问："),
      );
      promptList.forEach((followUp) => {
        const chip = createElement("button", "suggest-chip", followUp);
        chip.type = "button";
        chip.addEventListener("click", () => {
          input.value = followUp;
          input.focus();
        });
        suggestions.append(chip);
      });
    }
  } catch (error) {
    appendFollowUpMessage("assistant", { answer: `追问失败：${error instanceof Error ? error.message : "请稍后重试"}` });
  } finally {
    send.disabled = false;
  }
}

function createPortraitCard(title, blockClass) {
  const card = createElement("section", `portrait-card portrait-${blockClass}`);
  const heading = createElement("div", "portrait-card-heading");
  heading.append(createElement("h2", "", title));
  const body = createElement("div", "portrait-card-body");
  card.append(heading, body);
  return card;
}

// ---------- 题库页（题单广场：知识点题单卡片 → 题单详情刷题）----------

let bankAllQuestions = [];
let bankFilterKp = "";
let bankCategory = "all";
let bankKpMastery = {};   // knowledge_point_id -> 掌握度（来自学习路径）

async function loadBank() {
  const listView = document.querySelector("#bank-list-view");
  const detailView = document.querySelector("#bank-detail-view");
  if (listView) listView.hidden = false;
  if (detailView) detailView.hidden = true;
  // 从学习路径取各知识点掌握度（进度环数据）
  bankKpMastery = {};
  const pathItems = Array.isArray(state.learningPath?.items) ? state.learningPath.items : [];
  pathItems.forEach((item) => {
    if (item && item.knowledge_point_id) {
      bankKpMastery[item.knowledge_point_id] = Number(item.mastery) || 0;
    }
  });
  const grid = document.querySelector("#bank-sheet-grid");
  if (grid) grid.replaceChildren(createElement("p", "empty-state", "正在加载题单…"));
  try {
    const data = await window.workflowBackend.getBankQuestions();
    bankAllQuestions = (data && data.questions) || [];
    renderBankSheets();
  } catch (error) {
    if (grid) grid.replaceChildren(createElement("p", "empty-state", `题库加载失败：${error.message || "请稍后重试"}`));
  }
}

// 题单列表（洛谷风格卡片网格）：按知识点分组，显示掌握度进度环
async function renderWrongBook() {
  const grid = document.querySelector("#bank-sheet-grid");
  if (!grid) return;
  const kpMap = new Map();
  bankAllQuestions.forEach((q) => {
    if (!kpMap.has(q.knowledge_point_id)) {
      kpMap.set(q.knowledge_point_id, q.knowledge_point_name || q.knowledge_point_id);
    }
  });
  grid.replaceChildren(createElement("p", "empty-state", "正在加载错题本…"));
  try {
    const records = await window.workflowBackend.getRecords();
    const wrong = (records && records.attempts || [])
      .filter((entry) => entry.status === "incorrect")
      .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    // 只保留每题最近一次错答
    const seen = new Set();
    const items = wrong.filter((entry) => {
      const key = entry.source_question_id || entry.title || entry.attempt_id;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    const count = document.querySelector("#bank-count");
    if (count) count.textContent = String(items.length);
    const badge = document.querySelector("#bank-count-badge");
    if (badge) badge.textContent = `${items.length} 题`;
    if (!items.length) {
      grid.replaceChildren(createElement("p", "empty-state", "暂无错题，继续保持！"));
      return;
    }
    const list = createElement("div", "wrong-book-list");
    items.forEach((entry) => {
      const kpId = entry.knowledge_point_id || "";
      const kpName = kpMap.get(kpId) || kpId || "";
      const row = createElement("article", "wrong-book-item");
      row.append(
        createElement("strong", "", entry.title || "练习作答"),
        createElement("span", "wrong-book-meta", `${kpName} · ${new Date(entry.created_at).toLocaleString("zh-CN")}`),
      );
      const actions = createElement("div", "wrong-book-actions");
      const retry = createElement("button", "secondary-button", "去重做");
      retry.type = "button";
      retry.addEventListener("click", () => { if (kpId) openBankSheet(kpId, kpName || kpId); });
      const learn = createElement("button", "secondary-button", "去学习");
      learn.type = "button";
      learn.addEventListener("click", () => { if (kpId) jumpToKnowledge(kpId, kpName || kpId); });
      actions.append(retry, learn);
      row.append(actions);
      list.append(row);
    });
    grid.replaceChildren(list);
  } catch (error) {
    grid.replaceChildren(createElement("p", "empty-state", "错题本加载失败，请稍后重试。"));
  }
}

function renderBankSheets() {
  const grid = document.querySelector("#bank-sheet-grid");
  if (!grid) return;
  const kpMap = new Map();
  bankAllQuestions.forEach((q) => {
    if (!kpMap.has(q.knowledge_point_id)) {
      kpMap.set(q.knowledge_point_id, q.knowledge_point_name || q.knowledge_point_id);
    }
  });
  let sheets = [...kpMap.entries()].map(([kpId, name]) => {
    const questions = bankAllQuestions.filter((q) => q.knowledge_point_id === kpId);
    const mastery = bankKpMastery[kpId] ?? 0;
    return { kpId, name, count: questions.length, mastery };
  });
  // 分类筛选（薄弱/巩固/进阶）
  if (bankCategory === "weak") sheets = sheets.filter((s) => s.mastery < 40);
  if (bankCategory === "partial") sheets = sheets.filter((s) => s.mastery >= 40 && s.mastery < 80);
  if (bankCategory === "mastered") sheets = sheets.filter((s) => s.mastery >= 80);
  const count = document.querySelector("#bank-count");
  if (count) count.textContent = String(sheets.length);
  const badge = document.querySelector("#bank-count-badge");
  if (badge) badge.textContent = `${bankAllQuestions.length} 题`;
  if (!sheets.length) {
    grid.replaceChildren(createElement("p", "empty-state", "当前分类下暂无题单，换个分类看看"));
    return;
  }
  const cards = sheets.map((sheet, index) => {
    const card = createElement("article", "bank-sheet-card");
    card.dataset.kp = sheet.kpId;
    // 序号徽章
    const number = createElement("span", "bank-sheet-no", `#${String(index + 1).padStart(2, "0")}`);
    // 进度环（掌握度）
    const ring = createElement("span", "bank-sheet-ring");
    const pct = Math.max(0, Math.min(100, Math.round(sheet.mastery)));
    const stateCls = pct >= 80 ? "mastered" : pct >= 40 ? "partial" : "weak";
    ring.className = `bank-sheet-ring ${stateCls}`;
    ring.innerHTML = `<svg viewBox="0 0 36 36" aria-hidden="true">
      <circle class="ring-track" cx="18" cy="18" r="15.5"></circle>
      <circle class="ring-value" cx="18" cy="18" r="15.5"
        stroke-dasharray="${pct * 0.98} 100"></circle>
    </svg><span>${pct}%</span>`;
    const body = createElement("div", "bank-sheet-body");
    body.append(
      createElement("strong", "", sheet.name),
      createElement("small", "", `${sheet.count} 题 · ${pct >= 80 ? "掌握良好" : pct >= 40 ? "巩固中" : "建议优先学习"}`),
    );
    card.append(number, ring, body, createElement("i", "bank-sheet-arrow", ""));
    card.querySelector(".bank-sheet-arrow").innerHTML = '<i data-lucide="chevron-right"></i>';
    card.addEventListener("click", () => openBankSheet(sheet.kpId, sheet.name));
    return card;
  });
  grid.replaceChildren(...cards);
  if (window.lucide) window.lucide.createIcons();
}

// 打开题单详情：展示该知识点题目列表
function openBankSheet(kpId, kpName) {
  bankFilterKp = kpId;
  const listView = document.querySelector("#bank-list-view");
  const detailView = document.querySelector("#bank-detail-view");
  if (listView) listView.hidden = true;
  if (detailView) detailView.hidden = false;
  const kpLabel = document.querySelector("#bank-detail-kp");
  if (kpLabel) kpLabel.textContent = kpId || "";
  const nameEl = document.querySelector("#bank-detail-name");
  if (nameEl) nameEl.textContent = kpName || "知识点";
  renderBankQuestions();
}

function closeBankSheet() {
  bankFilterKp = "";
  const listView = document.querySelector("#bank-list-view");
  const detailView = document.querySelector("#bank-detail-view");
  if (listView) listView.hidden = false;
  if (detailView) detailView.hidden = true;
  renderBankSheets();
}

function shuffleBankQuestions() {
  const questions = bankAllQuestions
    .filter((q) => q.knowledge_point_id === bankFilterKp)
    .slice();
  for (let i = questions.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [questions[i], questions[j]] = [questions[j], questions[i]];
  }
  renderBankQuestions(questions);
}

function renderBankQuestions(ordered) {
  const list = document.querySelector("#bank-question-list");
  if (!list) return;
  const questions = ordered || bankAllQuestions.filter((q) => q.knowledge_point_id === bankFilterKp);
  const countEl = document.querySelector("#bank-detail-count");
  if (countEl) countEl.textContent = `共 ${questions.length} 道题`;
  if (!questions.length) {
    list.replaceChildren(createElement("p", "empty-state", "该知识点暂无题目"));
    return;
  }
  const cards = questions.map((q) => {
    const card = createElement("article", "bank-question-card");
    card.dataset.questionId = q.question_id;
    const meta = createElement("div", "bank-q-meta");
    meta.append(
      createElement("span", "bank-q-kp", q.knowledge_point_name || ""),
      createElement("span", "bank-q-diff", `难度 ${"★".repeat(Math.max(1, Number(q.difficulty) || 1))}`),
    );
    const title = createElement("h3", "bank-q-title", q.title || "");
    const optionsBox = createElement("div", "bank-q-options");
    Object.entries(q.options || {}).forEach(([key, text]) => {
      const label = createElement("label", "check-option");
      const input = document.createElement("input");
      input.type = "radio";
      input.name = `bank-answer-${q.question_id}`;
      input.value = key;
      label.append(input, createElement("span", "", key.toUpperCase()), createElement("span", "", String(text)));
      optionsBox.append(label);
    });
    const feedback = createElement("div", "bank-q-feedback");
    feedback.hidden = true;
    const actions = createElement("div", "bank-q-actions");
    const submit = createElement("button", "primary-button", "提交答案");
    submit.type = "button";
    submit.addEventListener("click", () => handleBankAnswer(q, optionsBox, feedback, submit));
    const learn = createElement("button", "secondary-button", "去学习该知识点");
    learn.type = "button";
    learn.hidden = true;
    learn.addEventListener("click", () => {
      state.learningGoal = state.learningGoal || {};
      state.currentKnowledgePointId = q.knowledge_point_id;
      state.currentKnowledgePointTitle = q.knowledge_point_name || "";
      requestLearning("initialize_learning", {
        source: "bank_practice",
        target_knowledge_point_id: q.knowledge_point_id,
      }).then(() => setPage("learning"));
    });
    actions.append(submit, learn);
    card.append(meta, title, optionsBox, feedback, actions);
    return card;
  });
  list.replaceChildren(...cards);
}

async function handleBankAnswer(question, optionsBox, feedback, submit) {
  const selected = optionsBox.querySelector('input[type="radio"]:checked');
  if (!selected) {
    showToast("请先选择一个选项");
    return;
  }
  submit.disabled = true;
  try {
    const result = await window.workflowBackend.checkBankAnswer(question.question_id, selected.value);
    const correct = Boolean(result.correct);
    feedback.hidden = false;
    feedback.className = `bank-q-feedback ${correct ? "correct" : "incorrect"}`;
    const expected = result.correct_answer ? `（正确答案：${String(result.correct_answer).toUpperCase()}）` : "";
    feedback.replaceChildren(
      createElement("strong", "", correct ? "回答正确" : "回答错误"),
      createElement("p", "", `${result.explanation || ""} ${expected}`.trim()),
    );
    const learn = feedback.parentElement.querySelector(".secondary-button");
    if (learn) learn.hidden = false;
    optionsBox.querySelectorAll('input[type="radio"]').forEach((input) => { input.disabled = true; });
    if (window.lucide) window.lucide.createIcons();
  } catch (error) {
    showToast(`判定失败：${error.message || "请稍后重试"}`);
  } finally {
    submit.disabled = false;
  }
}

// ---------- 个人中心 ----------

function loadProfilePage() {
  const profile = state.profile || {};
  const avatar = document.querySelector("#profile-avatar-text");
  if (avatar) avatar.textContent = (profile.display_name || "林").slice(0, 1);
  const name = document.querySelector("#profile-page-name");
  if (name) name.textContent = profile.display_name || "林同学";
  const id = document.querySelector("#profile-page-id");
  if (id) id.textContent = profile.student_id || window.workflowBackend.studentId;
  const program = document.querySelector("#profile-page-program");
  if (program) program.textContent = profile.program_name || "Java 面向对象程序设计实训";
  const goalName = document.querySelector("#profile-goal-name");
  const goalDesc = document.querySelector("#profile-goal-desc");
  const goal = state.learningGoal || {};
  if (goalName) goalName.textContent = goal.goal_name || "完成 Java 面向对象成绩管理实训";
  if (goalDesc) {
    const goalTypes = {
      competition: "按大赛标准训练，路径侧重综合应用与竞赛题型。",
      certification: "按 1+X 考点全覆盖训练，路径侧重认证考点。",
      daily: "按日常查漏补缺训练，路径侧重薄弱点补齐。",
      course: "围绕当前实训课程内容持续学习。",
    };
    goalDesc.textContent = goalTypes[goal.goal_type] || goalTypes.course;
  }
}

function openOnboarding(force = false) {
  const overlay = document.querySelector("#onboarding-overlay");
  if (!overlay) return;
  if (!force && localStorage.getItem("zhixing_onboarding_done") === "1") return;
  overlay.hidden = false;
  overlay.classList.add("show");
  // 切换目标场景（force）提供退出路径；首次引导必须完成，不显示取消
  const cancel = document.querySelector("#onboarding-cancel");
  if (cancel) cancel.hidden = !force;
  // 默认选中当前/竞赛目标
  const initialGoal = state.diagnosisGoal || "competition";
  overlay.querySelectorAll(".goal-card").forEach((card) => {
    const active = card.dataset.goal === initialGoal;
    card.classList.toggle("selected", active);
    card.setAttribute("aria-pressed", String(active));
  });
  if (window.lucide) window.lucide.createIcons();
}

function closeOnboarding() {
  const overlay = document.querySelector("#onboarding-overlay");
  if (!overlay) return;
  overlay.hidden = true;
  overlay.classList.remove("show");
}

// 首次引导：选中目标 → 写入学习目标 → 进入测评页（只出现一次）
function bindCustomGoalInputs() {
  // 事件委托 + 一次性绑定：onboarding 弹窗与诊断页侧边栏的自定义目标输入共用
  if (window.__customGoalBound) return;
  window.__customGoalBound = true;
  document.addEventListener("submit", async (event) => {
    const form = event.target.closest?.(".custom-goal-form");
    if (!form) return;
    event.preventDefault();
    const input = form.querySelector(".custom-goal-input");
    const resultEl = form.querySelector(".custom-goal-result");
    const submitBtn = form.querySelector(".custom-goal-submit");
    const text = input.value.trim();
    if (!text) {
      resultEl.className = "custom-goal-result warn";
      resultEl.textContent = "请先输入你的学习目标";
      resultEl.hidden = false;
      return;
    }
    submitBtn.disabled = true;
    resultEl.hidden = true;
    try {
      const result = await window.workflowBackend.analyzeGoal(text);
      if (result.matched) {
        state.diagnosisGoal = result.diagnosis_goal;
        state.learningGoal = result.goal;
        const scope = form.closest(".onboarding-modal, .diagnosis-goal-panel");
        scope?.querySelectorAll(".goal-card").forEach((card) => {
          const active = card.dataset.goal === result.diagnosis_goal;
          card.classList.toggle("selected", active);
          card.setAttribute("aria-pressed", String(active));
        });
        resultEl.className = "custom-goal-result ok";
        resultEl.textContent =
          `已识别：${result.goal.goal_name}（置信度 ${Math.round((result.confidence || 0) * 100)}%）`;
      } else {
        resultEl.className = "custom-goal-result warn";
        resultEl.textContent = result.clarification || "未能识别目标，请换一种描述或直接选择上方目标。";
      }
    } catch (error) {
      resultEl.className = "custom-goal-result warn";
      resultEl.textContent = error instanceof Error ? error.message : "目标识别失败，请稍后重试。";
    } finally {
      submitBtn.disabled = false;
      resultEl.hidden = false;
    }
  });
}

function bindOnboarding() {
  const overlay = document.querySelector("#onboarding-overlay");
  if (!overlay) return;
  overlay.querySelectorAll(".goal-card").forEach((card) => {
    card.addEventListener("click", () => {
      overlay.querySelectorAll(".goal-card").forEach((c) => {
        c.classList.remove("selected");
        c.setAttribute("aria-pressed", "false");
      });
      card.classList.add("selected");
      card.setAttribute("aria-pressed", "true");
      if (card.dataset.goal) state.diagnosisGoal = card.dataset.goal;
      const goalByDiagnosis = {
        competition: { goal_id: "GOAL-JAVA-COMPETITION", goal_type: "competition", goal_name: "备战世界职业院校技能大赛" },
        certification: { goal_id: "GOAL-JAVA-CERT", goal_type: "certification", goal_name: "1+X Java 应用开发认证" },
        daily: { goal_id: "GOAL-JAVA-DAILY", goal_type: "daily", goal_name: "日常技能提升" },
      };
      const mapped = goalByDiagnosis[card.dataset.goal];
      if (mapped) state.learningGoal = mapped;
    });
  });
  const confirm = document.querySelector("#onboarding-confirm");
  if (confirm) {
    confirm.addEventListener("click", () => {
      closeOnboarding();
      localStorage.setItem("zhixing_onboarding_done", "1");
      // 重置诊断会话，强制进入新一轮测评
      state.diagnosisQuestions = [];
      state.diagnosisStats = { correct: 0, wrong: 0, skipped: 0, done: false };
      state.diagnosisIndex = 0;
      setPage("diagnosis");
    });
  }
  const cancel = document.querySelector("#onboarding-cancel");
  if (cancel) {
    cancel.addEventListener("click", () => {
      closeOnboarding();
      if (state.page !== "profile") setPage("profile");
    });
  }
}

function loadPortrait() {
  const root = document.querySelector("#portrait-root");
  root.replaceChildren(createElement("p", "empty-state", "画像加载中…"));
  window.workflowBackend.getPortrait().then((data) => {
    state.portraitData = data;
    renderPortrait(data);
  }).catch((error) => {
    root.replaceChildren(createElement("p", "empty-state", "画像数据加载失败，请确认后端服务已启动。"));
  });
}

function renderPortrait(data) {
  const root = document.querySelector("#portrait-root");
  root.replaceChildren();
  [
    renderPortraitEvidence(data),
    renderPortraitIdentity(data),
    renderPortraitAbilities(data),
    renderPortraitKnowledge(data),
    renderPortraitWeakPoints(data),
    renderPortraitStyle(data),
    renderPortraitGrowth(data),
    renderPortraitRecommendations(data),
  ].forEach((block) => root.append(block));
  lucide.createIcons();
}

function renderPortraitEvidence(data) {
  // 画像数字溯源：展示计算掌握度的来源事件（作答/讲解）
  const items = Array.isArray(data && data.data_evidence) ? data.data_evidence : [];
  const card = createPortraitCard("数据来源", "evidence");
  const body = card.querySelector(".portrait-card-body");
  if (!items.length) {
    body.append(createElement("p", "empty-state", "暂无学习记录，画像数字将在作答/学习后生成"));
    return card;
  }
  // 状态枚举 → 中文（避免英文标识直接暴露给用户）
  const statusLabels = {
    correct: "回答正确",
    incorrect: "回答错误",
    skipped: "已跳过",
    concept_guidance: "概念引导",
    targeted_explanation: "针对性讲解",
    error_analysis: "错误归因",
    step_by_step: "分步讲解",
    example_driven: "案例讲解",
  };
  const list = createElement("div", "evidence-list");
  items.forEach((entry) => {
    const row = createElement("div", "evidence-item");
    const badge = createElement("span", `evidence-type ${entry.type === "讲解" ? "talk" : ""}`, entry.type || "事件");
    const bodyWrap = createElement("div", "evidence-body");
    bodyWrap.append(createElement("strong", "", entry.title || "学习记录"));
    const statusKey = String(entry.status || "").toLowerCase().replace(/\s+/g, "_");
    const statusText = statusLabels[statusKey] || entry.status || "";
    const meta = [statusText, entry.knowledge_point_id ? `知识点 ${entry.knowledge_point_id}` : ""].filter(Boolean);
    if (entry.created_at) meta.push(String(entry.created_at).slice(0, 10));
    bodyWrap.append(createElement("small", "", meta.join(" · ")));
    row.append(badge, bodyWrap);
    list.append(row);
  });
  body.append(
    createElement("p", "evidence-note", "以上画像数字由这些学习记录计算得出，可追溯、可验证。"),
    list,
  );
  return card;
}

function masteryColor(mastery) {
  if (mastery >= 80) return "#16a34a";
  if (mastery >= 60) return "#2563eb";
  if (mastery >= 40) return "#f59e0b";
  return "#dc2626";
}

function jumpToKnowledge(knowledgeId, name) {
  setPage("learning");
  const button = Array.from(document.querySelectorAll("#path-list button[data-lesson]")).find(
    (element) => element.dataset.knowledgePointId === knowledgeId,
  );
  if (button && !button.disabled) button.click();
  showToast(name ? `已定位到知识点：${name}` : "已回到学习中心");
}

function renderPortraitIdentity(data) {
  const identity = data.identity || {};
  const kpi = identity.kpi || {};
  const goal = identity.learning_goal || {};
  const card = createPortraitCard("身份与目标", "identity");
  const body = card.querySelector(".portrait-card-body");
  const kpiGrid = createElement("div", "kpi-grid");
  [
    ["总体掌握度", `${kpi.overall_mastery ?? 0}%`],
    ["已掌握知识点", kpi.mastered_knowledge_points || "0/0"],
    ["连续学习天数", `${kpi.streak_days ?? 0} 天`],
    ["本月讲解次数", `${kpi.lesson_count_this_month ?? 0} 次`],
  ].forEach(([label, value]) => {
    const item = createElement("div", "kpi-item");
    item.append(createElement("span", "kpi-label", label), createElement("strong", "", value));
    kpiGrid.append(item);
  });
  const progress = Math.max(0, Math.min(100, Math.round((Number(goal.goal_progress) || 0) * 100)));
  const ring = createElement("svg", "goal-ring");
  ring.setAttribute("viewBox", "0 0 40 40");
  ring.innerHTML = `<circle class="goal-ring-track" cx="20" cy="20" r="16"></circle><circle class="goal-ring-value" cx="20" cy="20" r="16" style="stroke-dasharray:${progress} 100"></circle><text x="20" y="23" text-anchor="middle" class="goal-ring-text">${progress}%</text>`;
  const copy = createElement("div", "goal-ring-copy");
  copy.append(createElement("small", "", "当前学习目标"), createElement("strong", "", goal.goal_name || "未设定目标"));
  const goalRow = createElement("div", "goal-ring-row");
  const goalTrack = createElement("div", "goal-mini-track");
  const goalFill = createElement("span", "goal-mini-fill");
  goalFill.style.width = `${progress}%`;
  goalTrack.append(goalFill);
  copy.append(goalTrack);
  goalRow.append(ring, copy);
  body.append(kpiGrid, goalRow);
  return card;
}

function renderPortraitAbilities(data) {
  const abilities = data.abilities || {};
  const dimensions = Array.isArray(abilities.dimensions) ? abilities.dimensions : [];
  const card = createPortraitCard("能力结构总览", "abilities");
  const body = card.querySelector(".portrait-card-body");
  if (!dimensions.length) {
    body.append(createElement("p", "empty-state", "暂无能力评分"));
    return card;
  }
  const size = 280;
  const center = size / 2;
  const radius = 100;
  const sides = dimensions.length;
  const angle = (index) => (Math.PI * 2 * index) / sides - Math.PI / 2;
  const point = (index, ratio) => {
    const x = center + radius * ratio * Math.cos(angle(index));
    const y = center + radius * ratio * Math.sin(angle(index));
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  };
  const grid = [0.33, 0.66, 1].map((ratio) =>
    `<polygon points="${dimensions.map((_, index) => point(index, ratio)).join(" ")}" class="radar-grid"></polygon>`,
  ).join("");
  const valuePoints = dimensions
    .map((dimension, index) => point(index, Math.max(0.05, Math.min(1, (Number(dimension.score) || 0) / 100))))
    .join(" ");
  const labels = dimensions.map((dimension, index) => {
    const [x, y] = point(index, 1.22).split(",");
    return `<text x="${x}" y="${y}" text-anchor="middle" class="radar-label">${dimension.name}</text>`;
  }).join("");
  const svg = createElement("svg", "radar-chart");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.innerHTML = `${grid}<polygon points="${valuePoints}" class="radar-value"></polygon>${labels}`;
  body.append(svg);
  if (abilities.is_fallback) {
    body.append(createElement("small", "data-note", "六维评分为本地估算，接入星辰画像工作流后替换为智能评分。"));
  }
  return card;
}

function renderPortraitKnowledge(data) {
  const knowledge = data.knowledge_mastery || {};
  const nodes = Array.isArray(knowledge.nodes) ? knowledge.nodes : [];
  const edges = Array.isArray(knowledge.edges) ? knowledge.edges : [];
  const card = createPortraitCard("知识点掌握度图谱", "knowledge");
  const body = card.querySelector(".portrait-card-body");
  if (!nodes.length) {
    body.append(createElement("p", "empty-state", "暂无知识点数据"));
    return card;
  }
  const svg = createElement("svg", "knowledge-graph");
  svg.setAttribute("viewBox", "0 0 400 230");
  const positions = nodes.map((_, index) => {
    if (nodes.length <= 3) {
      // 少量节点用三角形/环形布局，避免横向一条线造成的空洞
      const angle = Math.PI / 2 + (2 * Math.PI * index) / nodes.length;
      const radius = 100;
      return {
        x: 200 + radius * Math.cos(angle),
        y: 112 + radius * Math.sin(angle),
      };
    }
    return {
      x: 50 + (300 / Math.max(1, nodes.length - 1)) * index,
      y: 115 + (index % 2 === 0 ? -38 : 38),
    };
  });
  // 同心网格圈：填充少量节点时的视觉留白
  const ringMarkup = [48, 84, 118]
    .map((r) => `<circle cx="200" cy="112" r="${r}" class="graph-ring"></circle>`)
    .join("");
  const edgeMarkup = edges.map((edge) => {
    const from = nodes.findIndex((node) => node.id === edge.from);
    const to = nodes.findIndex((node) => node.id === edge.to);
    if (from < 0 || to < 0) return "";
    return `<line x1="${positions[from].x}" y1="${positions[from].y}" x2="${positions[to].x}" y2="${positions[to].y}" class="graph-edge"></line>`;
  }).join("");
  const nodeMarkup = nodes.map((node, index) => {
    const label = node.name || node.id || "";
    // 智能断行：优先在"与/和/及"后断开，避免词义破碎；每行不超过 6 字
    const labelLines = splitKnowledgeLabel(label);
    const labelY = nodes.length > 3
      ? (index % 2 === 0 ? 26 : 204)
      : positions[index].y + (index % 2 === 0 ? 26 : -26);
    const labelTspans = labelLines
      .map((line, lineIndex) =>
        `<tspan x="${positions[index].x}" dy="${lineIndex === 0 ? 0 : 11}">${line}</tspan>`,
      )
      .join("");
    return `<g class="graph-node" data-knowledge="${node.id}" data-knowledge-name="${label}">
      <circle cx="${positions[index].x}" cy="${positions[index].y}" r="22" fill="${masteryColor(Number(node.mastery))}"></circle>
      <text x="${positions[index].x}" y="${positions[index].y + 4}" text-anchor="middle" class="graph-node-text">${Number(node.mastery) || 0}%</text>
      <text x="${positions[index].x}" y="${labelY}" text-anchor="middle" class="graph-node-label">${labelTspans}</text>
    </g>`;
  }).join("");
  svg.innerHTML = `${ringMarkup}${edgeMarkup}${nodeMarkup}`;
  svg.addEventListener("click", (event) => {
    const group = event.target.closest(".graph-node");
    if (group) jumpToKnowledge(group.dataset.knowledge, group.dataset.knowledgeName);
  });
  body.append(svg);
  return card;
}

function renderPortraitWeakPoints(data) {
  const weakPoints = data.weak_points || {};
  const tags = Array.isArray(weakPoints.tags) ? weakPoints.tags : [];
  const breakdown = Array.isArray(weakPoints.error_breakdown) ? weakPoints.error_breakdown : [];
  const card = createPortraitCard("薄弱点与误解", "weakpoints");
  const body = card.querySelector(".portrait-card-body");
  if (tags.length) {
    const cloud = createElement("div", "word-cloud");
    tags.forEach((item, index) => {
      const word = createElement("span", "cloud-word", String(item.tag || ""));
      const weight = Number(item.weight) || 0.5;
      word.style.fontSize = `${Math.round(14 + weight * 14)}px`;
      word.style.transform = `rotate(${(index % 3 - 1) * 4}deg)`;
      cloud.append(word);
    });
    body.append(cloud);
  } else {
    const weakEmpty = createElement("div", "weakpoint-empty");
    const weakIcon = createElement("i", "", "");
    weakIcon.setAttribute("data-lucide", "alert-triangle");
    weakEmpty.append(weakIcon, createElement("strong", "", "暂无误解标签"), createElement("p", "", "完成测验后自动生成"));
    body.append(weakEmpty);
  }
  if (breakdown.length) {
    const bars = createElement("div", "error-bars");
    const max = Math.max(...breakdown.map((item) => item.count || 1));
    breakdown.forEach((item) => {
      const row = createElement("div", "error-bar-row");
      row.append(createElement("span", "", item.error_type || "mixed"));
      const track = createElement("div", "error-bar-track");
      const fill = createElement("span", "error-bar-fill");
      fill.style.width = `${Math.round(((item.count || 0) / max) * 100)}%`;
      track.append(fill);
      row.append(track, createElement("span", "error-bar-count", String(item.count || 0)));
      bars.append(row);
    });
    body.append(bars);
  }
  return card;
}

function renderPortraitStyle(data) {
  const style = data.learning_style || {};
  const card = createPortraitCard("学习风格与偏好", "style");
  const body = card.querySelector(".portrait-card-body");
  const labels = { visual: "视觉", auditory: "听觉", kinesthetic: "动觉", reading: "阅读" };
  const rows = createElement("div", "style-bars");
  ["visual", "auditory", "kinesthetic", "reading"].forEach((key) => {
    const value = Math.round((Number(style[key]) || 0) * 100);
    const row = createElement("div", "style-bar-row");
    row.append(createElement("span", "", labels[key]));
    const track = createElement("div", "style-bar-track");
    const fill = createElement("span", "style-bar-fill");
    fill.style.width = `${value}%`;
    track.append(fill);
    row.append(track, createElement("strong", "", `${value}%`));
    rows.append(row);
  });
  body.append(rows);
  body.append(createElement("p", "style-summary", style.summary || "偏好均衡"));
  if (style.is_fallback) {
    body.append(createElement("small", "data-note", "风格分布为占位数据，接入星辰画像工作流后替换。"));
  }
  return card;
}

function renderPortraitGrowth(data) {
  const growth = Array.isArray(data.growth) ? data.growth : [];
  const card = createPortraitCard("成长轨迹", "growth");
  const body = card.querySelector(".portrait-card-body");
  if (!growth.length) {
    body.append(createElement("p", "empty-state", "暂无讲解前后掌握度数据，完成讲解与阶段检查后生成。"));
    return card;
  }
  const list = createElement("div", "growth-list");
  growth.slice(-8).forEach((entry) => {
    const row = createElement("div", "growth-row");
    row.append(createElement("small", "", `${entry.at || ""} · ${entry.knowledge_point_id || ""}`));
    const bars = createElement("div", "growth-bars");
    const before = createElement("span", "growth-bar before");
    before.style.width = `${Math.max(2, Number(entry.mastery_before) || 0)}%`;
    const after = createElement("span", "growth-bar after");
    after.style.width = `${Math.max(2, Number(entry.mastery_after) || 0)}%`;
    bars.append(before, after);
    row.append(bars, createElement("strong", "", `${entry.mastery_before ?? "-"} → ${entry.mastery_after ?? "-"}`));
    list.append(row);
  });
  body.append(list);
  body.append(createElement("small", "data-note", "前后对比为估算值；讲解会话记录 mastery_before/after 后替换为真实数据。"));
  return card;
}

function renderPortraitRecommendations(data) {
  const recommendations = Array.isArray(data.recommendations) ? data.recommendations : [];
  const card = createPortraitCard("个性化推荐", "recommendations");
  card.classList.add("portrait-card--wide");
  const body = card.querySelector(".portrait-card-body");
  if (!recommendations.length) {
    body.append(createElement("p", "empty-state", "暂无推荐，完成诊断后生成。"));
    return card;
  }
  const grid = createElement("div", "recommend-grid");
  recommendations.forEach((recommendation) => {
    const item = createElement("button", "recommend-card");
    item.type = "button";
    item.append(
      createElement("span", "recommend-priority", `P${recommendation.priority || 1}`),
      createElement("strong", "", recommendation.title || "推荐学习"),
      createElement("p", "", recommendation.reason || ""),
    );
    item.addEventListener("click", () => {
      if (recommendation.knowledge_point_id) {
        jumpToKnowledge(recommendation.knowledge_point_id, recommendation.title || "");
      } else {
        showToast("该推荐需要先完成对应讲解");
      }
    });
    grid.append(item);
  });
  body.append(grid);
  return card;
}

function bindNewPageEvents() {
  document.querySelectorAll(".goal-card").forEach((card) => {
    card.addEventListener("click", () => {
      document.querySelectorAll(".goal-card").forEach((c) => {
        c.classList.remove("selected");
        c.setAttribute("aria-pressed", "false");
      });
      card.classList.add("selected");
      card.setAttribute("aria-pressed", "true");
      if (card.dataset.goal) state.diagnosisGoal = card.dataset.goal;
      // 诊断目标 → 学习目标（目标驱动路径）
      const goalByDiagnosis = {
        competition: { goal_id: "GOAL-JAVA-COMPETITION", goal_type: "competition", goal_name: "备战世界职业院校技能大赛" },
        certification: { goal_id: "GOAL-JAVA-CERT", goal_type: "certification", goal_name: "1+X Java 应用开发认证" },
        daily: { goal_id: "GOAL-JAVA-DAILY", goal_type: "daily", goal_name: "日常技能提升" },
      };
      const mapped = goalByDiagnosis[card.dataset.goal];
      if (mapped) state.learningGoal = mapped;
    });
  });
  document.querySelector("#diagnosis-submit")?.addEventListener("click", handleDiagnosisSubmit);
  document.querySelector("#diagnosis-skip")?.addEventListener("click", handleDiagnosisSkip);
  document.querySelector("#diagnosis-finish")?.addEventListener("click", () => {
    setPage("learning");
    window.workflowBackend.bootstrap().then((detail) => {
      applyBootstrap(detail);
    }).catch(() => {});
  });

  document.querySelectorAll(".clarify-option").forEach((option) => {
    option.addEventListener("click", () => {
      const clarify = document.querySelector("#chat-clarify");
      if (clarify) clarify.hidden = true;
    });
  });

  document.querySelector("#chat-input-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.querySelector("#chat-input");
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    appendChatMessage("user", message);
    try {
      const result = await window.workflowBackend.chat(message);
      if (result && result.status === "needs_clarification") {
        // 模糊提问 → 展示澄清选项（点击后填入输入框，不直接发送）
        const clarify = document.querySelector("#chat-clarify");
        if (clarify) {
          const options = (result.clarify_options || []).map(
            (opt) => `<button class="clarify-option" type="button" data-clarify="${opt.id}">${opt.label}</button>`,
          ).join("");
          clarify.querySelector(".clarify-note").textContent = result.message || "请选择你想了解的方向：";
          const list = clarify.querySelector("#chat-clarify-options") || clarify.querySelector(".clarify-options");
          if (list) list.innerHTML = options;
          clarify.hidden = false;
          clarify.querySelectorAll(".clarify-option").forEach((option) => {
            option.addEventListener("click", () => {
              const label = option.textContent.replace(/^[A-Za-z/]+\s*/, "").trim();
              input.value = label;
              input.focus();
              clarify.hidden = true;
            });
          });
        }
        appendChatMessage("assistant", result.message || "请选择你想了解的方向：");
        return;
      }
      const answer = (result && result.answer) || "暂未检索到相关内容，换个问法试试。";
      appendChatMessage("assistant", answer);
      if (result && Array.isArray(result.sources) && result.sources.length) {
        const sourceLine = result.sources
          .map((s) => `📚 ${s.title || "知识库"}${s.locator ? `（${s.locator}）` : ""}`)
          .join("\n");
        appendChatMessage("assistant", `来源：\n${sourceLine}`);
      }
      if (result && result.ai_generated) {
        appendChatMessage("assistant", "（本条为 AI 生成内容，依据知识库回答，供学习参考）");
      }
    } catch (error) {
      appendChatMessage("assistant", "查询失败，请稍后重试。");
    }
  });

  function appendChatMessage(role, text) {
    const messages = document.querySelector("#chat-messages");
    const clarify = document.querySelector("#chat-clarify");
    if (clarify) clarify.hidden = true;
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${role}`;
    const header = document.createElement("div");
    header.className = "chat-bubble-header";
    const roleLabel = document.createElement("span");
    roleLabel.className = "chat-role";
    roleLabel.innerHTML = role === "user"
      ? '<i data-lucide="user-round"></i> 我'
      : '<i data-lucide="bot"></i> 助手';
    const time = document.createElement("span");
    time.className = "chat-time";
    time.textContent = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    header.append(roleLabel, time);
    const body = document.createElement("div");
    body.className = "chat-bubble-body";
    body.textContent = text;
    bubble.append(header, body);
    messages.append(bubble);
    messages.scrollTop = messages.scrollHeight;
    if (window.lucide) window.lucide.createIcons();
  }

  document.querySelectorAll("#chat-suggestions .suggest-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const input = document.querySelector("#chat-input");
      if (input) input.value = chip.textContent.trim();
    });
  });

  document.querySelectorAll(".coverage-cell").forEach((cell) => {
    cell.addEventListener("click", () => {
      showToast(cell.title || cell.textContent?.trim() || "知识点详情");
    });
  });
}

function initialize() {
  initRichText();
  lucide.createIcons();
  bindEvents();
  bindSelectionFollowUp();
  bindNewPageEvents();
  bindOnboarding();
  bindCustomGoalInputs();
  setLearningMode("text");
  setReviewMode("text", false);
  // 首次进入：页面最中间弹出目标填写（只出现一次）
  openOnboarding(false);
}

window.addEventListener("app-bootstrap", ({ detail }) => applyBootstrap(detail));

window.addEventListener("workflow-loading", ({ detail }) => {
  document.body.classList.toggle("workflow-loading", detail.loading);
  const status = document.querySelector("#connection-status");
  status.innerHTML = detail.loading
    ? '<i data-lucide="loader-circle"></i> 正在调用个性化教学服务'
    : '<i data-lucide="cloud-check"></i> 学习状态已同步';
  lucide.createIcons();
});

window.addEventListener("backend-ready", ({ detail }) => {
  const modeLabel = detail.mode === "remote" ? "星辰工作流已连接" : "本地联调模式已连接";
  document.querySelector("#connection-status").innerHTML = `<i data-lucide="cloud-check"></i> ${modeLabel}`;
  lucide.createIcons();
});

window.addEventListener("workflow-error", ({ detail }) => {
  document.querySelector("#connection-status").innerHTML = '<i data-lucide="cloud-off"></i> 教学服务连接异常';
  showToast(detail.message || "后端请求失败");
  lucide.createIcons();
});

window.personalizedLearningUI = Object.freeze({
  applyWorkflowResult,
  requestLearning,
  requestReview,
  showMessage: showToast,
  events: WORKFLOW_EVENTS,
  statuses: WORKFLOW_STATUSES,
});

initialize();
