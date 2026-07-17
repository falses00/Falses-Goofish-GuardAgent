(function () {
  "use strict";

  const TOKEN_KEY = "xianyu-agent-access-token";
  const THEME_KEY = "guardagent-console-theme";
  const viewMetadata = {
    dashboard: {
      title: "运营总览",
      eyebrow: "Agent operations",
      description: "查看 Agent 决策质量、运行风险与最近活动。",
    },
    workbench: {
      title: "回复试跑",
      eyebrow: "Safe simulation",
      description: "输入真实买家问题，在不触达闲鱼的前提下检查回复与护栏。",
    },
    traces: {
      title: "决策记录",
      eyebrow: "Decision database",
      description: "按状态和意图筛选每一次 Agent 路由、护栏与证据。",
    },
    runtime: {
      title: "运行状态",
      eyebrow: "Runtime health",
      description: "检查 API、Worker 心跳、登录态与平台风控恢复路径。",
    },
  };
  const intentLabels = {
    price: "价格协商",
    tech: "商品咨询",
    default: "普通咨询",
  };
  const workerStateLabels = {
    registered: "已连接",
    connecting: "连接中",
    reconnecting: "重连中",
    heartbeat_timeout: "心跳超时",
    auth_failed: "认证失败",
  };
  const reasonLabels = {
    ok: "状态正常",
    status_missing: "尚无 Worker 快照",
    status_stale: "Worker 状态已过期",
    invalid_stale_after_seconds: "状态时效配置无效",
  };
  const workerErrorLabels = {
    XianyuRiskControlError: "闲鱼风控验证",
    AuthenticationError: "登录认证失败",
    ConnectionError: "网络连接失败",
    TimeoutError: "连接超时",
  };
  const fieldLabels = {
    user_msg: "买家消息",
    additional_user_msgs: "连续消息",
    request_id: "请求 ID",
    chat_id: "会话 ID",
    item_id: "商品 ID",
    user_id: "买家 ID",
    assistant_id: "卖家 ID",
    item_info: "商品信息",
    context: "对话上下文",
    persist_turn: "本地记忆选项",
  };
  const priceLabels = {
    buyer_offer: "买家出价",
    calculated_price: "建议成交价",
    min_price: "最低价",
    original_price: "原价",
    current_price: "当前报价",
    price_source: "价格来源",
    last_committed: "已承诺最低价",
    buyer_highest: "买家最高出价",
    decision: "决策",
    action: "处理动作",
    reason: "决策原因",
    source: "价格来源",
    accepted: "是否接受",
  };
  const knowledgeLabels = {
    matched: "是否命中",
    source: "知识来源",
    sources: "知识来源",
    matched_fields: "命中字段",
    fields: "命中字段",
    facts: "商品事实",
    query: "检索内容",
    reason: "命中说明",
  };

  const state = {
    access: { tokenRequired: false, docsEnabled: false },
    overview: null,
    traces: [],
    visibleTraces: [],
    selectedTraceTimestamp: null,
    latestReply: null,
    retryAfterToken: null,
    traceErrorIsAuth: false,
    activeView: "dashboard",
    viewScrollPositions: { dashboard: 0, workbench: 0, traces: 0, runtime: 0 },
  };

  const elements = {};

  class ApiError extends Error {
    constructor(status, payload, requestId) {
      const detail = payload && payload.detail;
      super(typeof detail === "string" ? detail : `HTTP ${status}`);
      this.name = "ApiError";
      this.status = status;
      this.payload = payload;
      this.requestId = requestId || "";
    }
  }

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    cacheElements();
    initializeTheme();
    bindEvents();
    activateView(viewFromHash(), { updateHash: false, focus: false });
    updateTokenIndicator();
    updateMessageCount();
    generateRequestId();
    loadDashboard();
  }

  function cacheElements() {
    const ids = [
      "pageEyebrow", "pageTitle", "pageDescription", "sidebarOverviewState", "sidebarTraceCount", "sidebarRuntimeState",
      "apiStatus", "workerStatus", "modeStatus", "refreshAllButton", "openTokenButton",
      "themeToggleButton", "globalSearch", "mobileNavButton", "closeSidebarButton", "mobileNavBackdrop",
      "appSidebar", "appWorkspace",
      "tokenIndicator", "globalNotice", "globalNoticeTitle", "globalNoticeMessage",
      "dismissNoticeButton", "runtimeAlert", "runtimeAlertLabel", "runtimeAlertTitle",
      "runtimeAlertMessage", "openRuntimeButton", "overviewUpdatedAt", "metricGrid", "workerMetric",
      "workerMetricNote", "heartbeatMetric", "heartbeatMetricNote", "traceMetric",
      "traceMetricNote", "guardrailMetric", "guardrailMetricNote", "replyForm",
      "userMessage", "userMessageCount", "userMessageError", "additionalMessages",
      "requestId", "generateRequestIdButton", "chatId", "itemId", "userId",
      "assistantId", "itemInfo", "itemInfoError", "conversationContext", "contextError",
      "persistTurn", "submitReplyButton", "resetReplyButton", "replyFeedback",
      "resultEmpty", "resultLoading", "resultContent", "copyReplyButton", "openLatestTraceButton", "resultBadges",
      "replyOutput", "replayNote", "decisionOutput", "priceOutput", "knowledgeOutput",
      "memoryOutput", "rawReplyOutput", "traceCount", "refreshTracesButton", "traceList",
      "traceSearch", "traceIntentFilter", "traceStatusFilter", "traceFilterSummary", "traceEmpty", "traceEmptyTitle",
      "traceEmptyMessage", "traceError", "traceErrorTitle", "traceErrorMessage", "traceErrorAction",
      "traceDetail", "traceDetailEmpty", "traceDetailContent", "traceDetailTime",
      "traceDetailTitle", "traceDetailIntent", "traceDetailMessage", "traceSections",
      "rawTraceOutput", "tokenDialog", "tokenForm", "closeTokenButton", "accessToken",
      "showToken", "tokenDialogStatus", "clearTokenButton", "refreshRuntimeButton",
      "runtimeDetails", "runtimeRecoverySteps", "runtimeRawOutput",
      "dashboardSafeRate", "dashboardSafeRateNote", "dashboardIntentBars", "dashboardTraceTable",
      "dashboardActivityList", "dashboardFocusStatus", "dashboardFocusTitle", "dashboardFocusMessage",
    ];
    ids.forEach((id) => {
      elements[id] = document.getElementById(id);
    });
  }

  function bindEvents() {
    document.querySelectorAll("[data-view]").forEach((button) => {
      button.addEventListener("click", () => {
        activateView(button.dataset.view, { updateHash: true, focus: true });
        closeMobileNav();
      });
    });
    document.querySelectorAll("[data-action-view]").forEach((button) => {
      button.addEventListener("click", () => activateView(button.dataset.actionView, { updateHash: true, focus: true }));
    });
    window.addEventListener("hashchange", () => activateView(viewFromHash(), { updateHash: false, focus: true }));
    window.addEventListener("resize", handleViewportChange);
    document.addEventListener("keydown", handleGlobalShortcut);
    elements.globalSearch.addEventListener("keydown", handleGlobalSearch);
    elements.themeToggleButton.addEventListener("click", toggleTheme);
    elements.mobileNavButton.addEventListener("click", openMobileNav);
    elements.closeSidebarButton.addEventListener("click", () => closeMobileNav());
    elements.mobileNavBackdrop.addEventListener("click", () => closeMobileNav());
    elements.refreshAllButton.addEventListener("click", () => loadDashboard(true));
    elements.refreshRuntimeButton.addEventListener("click", () => loadDashboard(true));
    elements.refreshTracesButton.addEventListener("click", () => loadTraces(true));
    elements.openRuntimeButton.addEventListener("click", () => activateView("runtime", { updateHash: true, focus: true }));
    elements.dismissNoticeButton.addEventListener("click", hideNotice);
    elements.openTokenButton.addEventListener("click", () => showTokenDialog());
    elements.closeTokenButton.addEventListener("click", closeTokenDialog);
    elements.tokenForm.addEventListener("submit", saveToken);
    elements.clearTokenButton.addEventListener("click", clearToken);
    elements.showToken.addEventListener("change", () => {
      elements.accessToken.type = elements.showToken.checked ? "text" : "password";
    });
    elements.tokenDialog.addEventListener("click", (event) => {
      if (event.target === elements.tokenDialog) {
        closeTokenDialog();
      }
    });
    elements.userMessage.addEventListener("input", () => {
      updateMessageCount();
      clearFieldError(elements.userMessage, elements.userMessageError);
    });
    elements.itemInfo.addEventListener("input", () => clearFieldError(elements.itemInfo, elements.itemInfoError));
    elements.conversationContext.addEventListener("input", () => clearFieldError(elements.conversationContext, elements.contextError));
    elements.generateRequestIdButton.addEventListener("click", generateRequestId);
    elements.replyForm.addEventListener("submit", submitReply);
    elements.replyForm.addEventListener("reset", () => window.setTimeout(resetReplyView, 0));
    elements.copyReplyButton.addEventListener("click", copyReply);
    elements.openLatestTraceButton.addEventListener("click", openLatestTrace);
    elements.traceSearch.addEventListener("input", applyTraceFilters);
    elements.traceIntentFilter.addEventListener("change", applyTraceFilters);
    elements.traceStatusFilter.addEventListener("change", applyTraceFilters);
    elements.traceList.addEventListener("click", selectTraceFromEvent);
    elements.dashboardTraceTable.addEventListener("click", selectDashboardTrace);
    elements.traceErrorAction.addEventListener("click", () => {
      if (state.traceErrorIsAuth) {
        state.retryAfterToken = () => loadTraces(true);
        showTokenDialog("访问 Trace 需要有效令牌。");
      } else {
        loadTraces(true);
      }
    });
  }

  function initializeTheme() {
    let savedTheme = "";
    try {
      savedTheme = window.localStorage.getItem(THEME_KEY) || "";
    } catch (error) {
      savedTheme = "";
    }
    const preferredTheme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
    applyTheme(savedTheme === "dark" || savedTheme === "light" ? savedTheme : preferredTheme);
  }

  function toggleTheme() {
    const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(nextTheme);
    try {
      window.localStorage.setItem(THEME_KEY, nextTheme);
    } catch (error) {
      // The visual theme still works when persistent browser storage is disabled.
    }
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    elements.themeToggleButton.setAttribute("aria-label", theme === "dark" ? "切换浅色模式" : "切换深色模式");
    elements.themeToggleButton.title = theme === "dark" ? "切换浅色模式" : "切换深色模式";
  }

  function openMobileNav() {
    document.body.classList.add("nav-open");
    elements.mobileNavBackdrop.hidden = false;
    elements.mobileNavButton.setAttribute("aria-expanded", "true");
    elements.appWorkspace.inert = true;
    elements.appSidebar.setAttribute("role", "dialog");
    elements.appSidebar.setAttribute("aria-modal", "true");
    window.requestAnimationFrame(() => elements.closeSidebarButton.focus());
  }

  function closeMobileNav(options) {
    const settings = { restoreFocus: true, ...(options || {}) };
    const wasOpen = document.body.classList.contains("nav-open");
    document.body.classList.remove("nav-open");
    elements.mobileNavBackdrop.hidden = true;
    elements.mobileNavButton.setAttribute("aria-expanded", "false");
    elements.appWorkspace.inert = false;
    elements.appSidebar.removeAttribute("role");
    elements.appSidebar.removeAttribute("aria-modal");
    if (wasOpen && settings.restoreFocus && window.innerWidth <= 960) {
      elements.mobileNavButton.focus({ preventScroll: true });
    }
  }

  function handleViewportChange() {
    if (window.innerWidth > 960 && document.body.classList.contains("nav-open")) {
      closeMobileNav({ restoreFocus: false });
    }
  }

  function trapMobileNavFocus(event) {
    if (event.key !== "Tab" || !document.body.classList.contains("nav-open") || window.innerWidth > 960) {
      return false;
    }
    const focusable = Array.from(elements.appSidebar.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => element.getClientRects().length > 0);
    if (!focusable.length) {
      event.preventDefault();
      return true;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !elements.appSidebar.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
      return true;
    }
    if (!event.shiftKey && (document.activeElement === last || !elements.appSidebar.contains(document.activeElement))) {
      event.preventDefault();
      first.focus();
      return true;
    }
    return false;
  }

  function handleGlobalShortcut(event) {
    if (trapMobileNavFocus(event)) {
      return;
    }
    if (event.key === "Escape" && document.body.classList.contains("nav-open")) {
      closeMobileNav();
      return;
    }
    const target = event.target;
    const isTyping = target instanceof HTMLInputElement
      || target instanceof HTMLTextAreaElement
      || target instanceof HTMLSelectElement
      || target.isContentEditable;
    if (event.key === "/" && !isTyping && !event.metaKey && !event.ctrlKey && !event.altKey) {
      event.preventDefault();
      elements.globalSearch.focus();
    }
  }

  function handleGlobalSearch(event) {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    elements.traceSearch.value = elements.globalSearch.value.trim();
    elements.traceIntentFilter.value = "";
    elements.traceStatusFilter.value = "";
    applyTraceFilters();
    activateView("traces", { updateHash: true, focus: true });
  }

  function viewFromHash() {
    const candidate = window.location.hash.replace(/^#/, "");
    return Object.prototype.hasOwnProperty.call(viewMetadata, candidate) ? candidate : "dashboard";
  }

  function activateView(view, options) {
    const targetView = Object.prototype.hasOwnProperty.call(viewMetadata, view) ? view : "dashboard";
    const settings = { updateHash: false, focus: false, ...(options || {}) };
    const previousView = state.activeView;
    if (previousView !== targetView && Object.prototype.hasOwnProperty.call(viewMetadata, previousView)) {
      state.viewScrollPositions[previousView] = window.scrollY;
    }
    state.activeView = targetView;

    document.querySelectorAll("[data-workspace-view]").forEach((section) => {
      section.hidden = section.dataset.workspaceView !== targetView;
    });
    document.querySelectorAll("[data-view]").forEach((button) => {
      const active = button.dataset.view === targetView;
      if (active) {
        button.setAttribute("aria-current", "page");
      } else {
        button.removeAttribute("aria-current");
      }
    });

    const metadata = viewMetadata[targetView];
    elements.pageEyebrow.textContent = metadata.eyebrow;
    elements.pageTitle.textContent = metadata.title;
    elements.pageDescription.textContent = metadata.description;
    elements.openRuntimeButton.hidden = targetView === "runtime";
    document.title = `${metadata.title} | 闲鱼卖家 Agent 操作台`;

    if (settings.updateHash && window.location.hash !== `#${targetView}`) {
      window.history.pushState(null, "", `#${targetView}`);
    }
    if (previousView !== targetView || settings.focus) {
      window.requestAnimationFrame(() => {
        if (settings.focus) {
          elements.pageTitle.focus({ preventScroll: true });
        }
        if (previousView !== targetView) {
          window.requestAnimationFrame(() => {
            window.scrollTo(0, state.viewScrollPositions[targetView] || 0);
          });
        }
      });
    }
  }

  function openLatestTrace() {
    const latest = state.traces[0];
    elements.traceSearch.value = "";
    elements.traceIntentFilter.value = "";
    elements.traceStatusFilter.value = "";
    state.selectedTraceTimestamp = latest ? latest.timestamp : null;
    applyTraceFilters();
    activateView("traces", { updateHash: true, focus: true });
  }

  async function loadDashboard(announce) {
    setButtonBusy(elements.refreshAllButton, true, "刷新中…");
    setOverviewLoading();
    setStatus(elements.apiStatus, "loading", "检查中");
    setStatus(elements.workerStatus, "loading", "检查中");
    setStatus(elements.modeStatus, "loading", "检查中");

    try {
      const access = await apiFetch("/api/access");
      state.access = {
        tokenRequired: Boolean(access.token_required),
        docsEnabled: Boolean(access.docs_enabled),
      };
      updateTokenIndicator();
    } catch (error) {
      showNotice("无法读取访问策略", describeGenericError(error), "error");
    }

    const traceRequest = state.access.tokenRequired && !getToken()
      ? Promise.resolve().then(() => {
        renderTraceError(new ApiError(401, { detail: "invalid_or_missing_access_token" }), { promptAuth: false });
        setTraceLoading(false);
        return {};
      })
      : loadTraces(false);
    const results = await Promise.allSettled([
      apiFetch("/api/overview"),
      traceRequest,
    ]);

    if (results[0].status === "fulfilled") {
      state.overview = results[0].value;
      renderOverview(state.overview);
      if (announce) {
        showNotice("状态已刷新", "运行快照和最近 Trace 已更新。", "ok", 3200);
      }
    } else {
      renderOverviewError(results[0].reason);
    }

    setButtonBusy(elements.refreshAllButton, false);
  }

  function setOverviewLoading() {
    elements.metricGrid.setAttribute("aria-busy", "true");
    [elements.workerMetric, elements.heartbeatMetric, elements.traceMetric, elements.guardrailMetric]
      .forEach((element) => {
        element.textContent = "读取中";
        element.classList.add("skeleton-text");
      });
    elements.overviewUpdatedAt.textContent = "正在读取本地运行快照";
    elements.sidebarOverviewState.textContent = "同步中";
    elements.sidebarRuntimeState.textContent = "检查中";
    elements.dashboardFocusStatus.textContent = "正在检查";
    delete elements.dashboardFocusStatus.dataset.tone;
    elements.dashboardFocusTitle.textContent = "读取当前运行风险";
    elements.dashboardFocusMessage.textContent = "操作台正在核对 Worker 快照与最近 Trace。";
  }

  function renderOverview(data) {
    const api = data && data.api ? data.api : {};
    const worker = data && data.worker ? data.worker : {};
    const workerSnapshot = worker.status && typeof worker.status === "object" ? worker.status : {};
    const traces = data && data.traces ? data.traces : {};
    const stateName = workerSnapshot.state || "unknown";
    const stateLabel = workerStateLabels[stateName] || (stateName === "unknown" ? "未知" : stateName);
    const reasonLabel = reasonLabels[worker.reason] || humanizeKey(worker.reason || "unknown");
    const lastHeartbeat = workerSnapshot.last_heartbeat_response_at || workerSnapshot.last_heartbeat_sent_at;

    setStatus(elements.apiStatus, api.healthy === false ? "error" : "ok", api.healthy === false ? "不可用" : "服务可用");
    setStatus(elements.workerStatus, worker.healthy ? "ok" : worker.reason === "status_missing" ? "warning" : "error", stateLabel);

    if (workerSnapshot.dry_run === true) {
      setStatus(elements.modeStatus, "ok", "Dry-run 开启");
    } else if (workerSnapshot.dry_run === false) {
      setStatus(elements.modeStatus, "warning", "真实发送开启");
    } else {
      setStatus(elements.modeStatus, "warning", "模式未知");
    }

    setMetric(elements.workerMetric, stateLabel);
    elements.workerMetricNote.textContent = worker.age_seconds == null
      ? reasonLabel
      : `${reasonLabel}，快照 ${formatDuration(worker.age_seconds * 1000)}前更新`;

    setMetric(elements.heartbeatMetric, lastHeartbeat ? formatRelativeTime(lastHeartbeat) : "暂无");
    elements.heartbeatMetricNote.textContent = lastHeartbeat ? formatDateTime(lastHeartbeat) : "Worker 尚未上报心跳";

    const sampleSize = numberOrZero(traces.sample_size);
    setMetric(elements.traceMetric, `${sampleSize} 条`);
    elements.traceMetricNote.textContent = traces.last_recorded_at
      ? `最近记录于 ${formatRelativeTime(traces.last_recorded_at)}`
      : "还没有生成 Trace";

    setMetric(
      elements.guardrailMetric,
      `${numberOrZero(traces.guardrail_count)} / ${numberOrZero(traces.fallback_count)}`,
    );
    elements.guardrailMetricNote.textContent = sampleSize ? `基于最近 ${sampleSize} 条记录` : "暂无可统计记录";

    elements.metricGrid.setAttribute("aria-busy", "false");
    elements.overviewUpdatedAt.textContent = `页面更新于 ${formatDateTime(Date.now())}`;
    elements.sidebarRuntimeState.textContent = workerSnapshot.last_error_type === "XianyuRiskControlError"
      ? "平台风控"
      : worker.healthy ? "运行正常" : stateLabel;
    elements.sidebarOverviewState.textContent = worker.healthy ? "正常" : "需处理";
    elements.sidebarTraceCount.textContent = `${sampleSize} 条`;
    renderRuntimeState(worker, workerSnapshot, stateLabel, reasonLabel, lastHeartbeat);
    renderDashboardInsights();

    if (state.access.tokenRequired && !getToken()) {
      showNotice("API 已启用访问保护", "运行总览可见，模拟回复和 Trace 需要先设置访问令牌。", "warning");
    }
  }

  function renderOverviewError(error) {
    state.overview = null;
    setStatus(elements.apiStatus, "error", "连接失败");
    setStatus(elements.workerStatus, "error", "无法读取");
    setStatus(elements.modeStatus, "warning", "模式未知");
    setMetric(elements.workerMetric, "不可用");
    setMetric(elements.heartbeatMetric, "不可用");
    setMetric(elements.traceMetric, "不可用");
    setMetric(elements.guardrailMetric, "不可用");
    elements.workerMetricNote.textContent = "未取得 Worker 快照";
    elements.heartbeatMetricNote.textContent = "请确认本地 API 已启动";
    elements.traceMetricNote.textContent = "未取得统计数据";
    elements.guardrailMetricNote.textContent = "未取得统计数据";
    elements.metricGrid.setAttribute("aria-busy", "false");
    elements.overviewUpdatedAt.textContent = "本次读取失败";
    elements.sidebarOverviewState.textContent = "离线";
    elements.sidebarRuntimeState.textContent = "读取失败";
    elements.runtimeAlert.hidden = false;
    elements.runtimeAlert.dataset.tone = "error";
    elements.runtimeAlertLabel.textContent = "API 连接失败";
    elements.runtimeAlertTitle.textContent = "本地操作台无法读取运行状态";
    elements.runtimeAlertMessage.textContent = "请确认 API 已启动，然后刷新状态。";
    elements.runtimeDetails.replaceChildren();
    elements.runtimeRecoverySteps.replaceChildren();
    elements.runtimeRawOutput.textContent = "";
    renderDashboardInsights();
    showNotice("无法连接本地 API", describeGenericError(error), "error");
  }

  function renderRuntimeState(worker, workerSnapshot, stateLabel, reasonLabel, lastHeartbeat) {
    const errorType = workerSnapshot.last_error_type || "";
    const errorLabel = workerErrorLabels[errorType] || errorType || "无";
    const ageLabel = worker.age_seconds == null ? "未知" : `${formatDuration(worker.age_seconds * 1000)}前`;
    const updatedAt = workerSnapshot.updated_at || null;

    renderDataList(elements.runtimeDetails, {
      "Worker 状态": stateLabel,
      "健康判断": worker.healthy ? "正常" : reasonLabel,
      "发送模式": workerSnapshot.dry_run === true ? "Dry-run" : workerSnapshot.dry_run === false ? "真实发送" : "未知",
      "最近错误": errorLabel,
      "快照时间": updatedAt ? formatDateTime(updatedAt) : "未记录",
      "快照距今": ageLabel,
      "最近心跳": lastHeartbeat ? formatDateTime(lastHeartbeat) : "未记录",
      "重连次数": workerSnapshot.reconnect_attempt ?? 0,
      "进程 PID": workerSnapshot.pid || "未记录",
    });
    elements.runtimeRawOutput.textContent = JSON.stringify(worker, null, 2);

    let steps = [
      "保持 Dry-run，先在回复工作台验证价格、事实与话术。",
      "刷新运行状态，确认 Worker 心跳与快照持续更新。",
      "只有在登录态、规则和 Trace 均正常后，才评估真实发送。",
    ];

    if (errorType === "XianyuRiskControlError") {
      steps = [
        "在闲鱼官方页面确认当前账号能够正常访问，并完成平台要求的验证。",
        "更新本地登录态后重启 Worker，再刷新本页确认心跳恢复。",
        "先保持 Dry-run 完成一次回复试跑，不要在风控未解除时反复重连。",
      ];
    } else if (workerSnapshot.state === "auth_failed") {
      steps = [
        "在闲鱼官方页面确认账号登录仍然有效。",
        "更新本地登录态并重启 Worker。",
        "刷新本页，确认状态变为“已连接”后再继续。",
      ];
    } else if (worker.reason === "status_stale") {
      steps = [
        "确认 Worker 进程仍在运行，并检查最近一条本地日志。",
        "重启 Worker 后刷新本页，观察快照时间与心跳是否推进。",
        "恢复前保持 Dry-run，避免使用过期状态判断真实发送能力。",
      ];
    }
    renderRecoverySteps(steps);

    if (!worker.healthy) {
      const riskControl = errorType === "XianyuRiskControlError";
      elements.runtimeAlert.hidden = false;
      elements.runtimeAlert.dataset.tone = worker.reason === "status_missing" ? "warning" : "error";
      elements.runtimeAlertLabel.textContent = riskControl ? "平台风控" : "Worker 异常";
      elements.runtimeAlertTitle.textContent = riskControl
        ? "闲鱼风控验证阻断了 Worker"
        : `${stateLabel}，当前不能视为可用`;
      elements.runtimeAlertMessage.textContent = riskControl
        ? `最近错误为 ${errorLabel}，快照更新于 ${ageLabel}。先完成官方验证，再更新登录态并重启 Worker。`
        : `${reasonLabel}，快照更新于 ${ageLabel}。打开运行状态可查看错误、心跳与恢复步骤。`;
    } else if (workerSnapshot.dry_run === false) {
      elements.runtimeAlert.hidden = false;
      elements.runtimeAlert.dataset.tone = "warning";
      elements.runtimeAlertLabel.textContent = "真实发送";
      elements.runtimeAlertTitle.textContent = "Worker 已开启真实发送";
      elements.runtimeAlertMessage.textContent = "回复工作台仍只做模拟，但在线 Worker 可能触达买家。操作前请确认规则与登录态。";
    } else {
      elements.runtimeAlert.hidden = true;
      delete elements.runtimeAlert.dataset.tone;
    }
  }

  function renderRecoverySteps(steps) {
    elements.runtimeRecoverySteps.replaceChildren();
    steps.forEach((step) => {
      const item = document.createElement("li");
      item.textContent = step;
      elements.runtimeRecoverySteps.append(item);
    });
  }

  async function loadTraces(announce) {
    setTraceLoading(true);
    try {
      const data = await apiFetch("/api/traces?limit=50");
      const records = Array.isArray(data.items) ? data.items.slice().reverse() : [];
      state.traces = records;
      state.traceErrorIsAuth = false;
      elements.sidebarTraceCount.textContent = `${records.length} 条`;
      applyTraceFilters();
      renderDashboardInsights();
      if (announce) {
        showNotice("Trace 已刷新", records.length ? `已读取最近 ${records.length} 条记录。` : "当前还没有 Trace。", "ok", 2800);
      }
      return data;
    } catch (error) {
      renderTraceError(error);
      throw error;
    } finally {
      setTraceLoading(false);
    }
  }

  function setTraceLoading(loading) {
    elements.refreshTracesButton.disabled = loading;
    elements.traceList.setAttribute("aria-busy", String(loading));
    if (loading && state.traces.length === 0) {
      elements.traceList.dataset.loading = "true";
      elements.traceCount.textContent = "读取中";
      elements.traceError.hidden = true;
      elements.traceEmpty.hidden = true;
    } else {
      delete elements.traceList.dataset.loading;
    }
  }

  function applyTraceFilters() {
    const query = elements.traceSearch.value.trim().toLocaleLowerCase("zh-CN");
    const intent = elements.traceIntentFilter.value;
    const status = elements.traceStatusFilter.value;
    const records = state.traces.filter((record) => {
      const trace = record && record.trace ? record.trace : {};
      if (intent && trace.intent !== intent) {
        return false;
      }
      if (status && getTraceStatus(trace).key !== status) {
        return false;
      }
      if (!query) {
        return true;
      }
      const searchable = [
        trace.user_msg,
        trace.chat_id,
        trace.routed_agent,
        trace.intent,
        intentLabels[trace.intent],
        ...(Array.isArray(trace.guardrails) ? trace.guardrails : []),
      ].filter(Boolean).join(" ").toLocaleLowerCase("zh-CN");
      return searchable.includes(query);
    });
    renderTraceList(records);
    elements.traceFilterSummary.textContent = state.traces.length === records.length
      ? `共 ${records.length} 条决策`
      : `显示 ${records.length} / ${state.traces.length} 条`;
  }

  function renderTraceList(records) {
    state.visibleTraces = records;
    elements.traceList.replaceChildren();
    elements.traceError.hidden = true;
    elements.traceCount.textContent = state.traces.length === records.length
      ? `${records.length} 条`
      : `${records.length} / ${state.traces.length} 条`;

    if (records.length === 0) {
      elements.traceEmpty.hidden = false;
      const filtered = state.traces.length > 0;
      elements.traceEmptyTitle.textContent = filtered ? "没有匹配的决策" : "暂无 Trace";
      elements.traceEmptyMessage.textContent = filtered
        ? "调整搜索词或意图筛选后再试。"
        : "完成一次模拟回复后，新的决策记录会出现在这里。";
      clearTraceDetail();
      return;
    }

    elements.traceEmpty.hidden = true;
    records.forEach((record, index) => {
      const trace = record && record.trace ? record.trace : {};
      const button = document.createElement("button");
      const top = document.createElement("span");
      const title = document.createElement("span");
      const titleGroup = document.createElement("span");
      const statusBadge = document.createElement("span");
      const time = document.createElement("time");
      const message = document.createElement("span");
      const meta = document.createElement("span");
      const selected = state.selectedTraceTimestamp
        ? record.timestamp === state.selectedTraceTimestamp
        : index === 0;

      button.type = "button";
      button.className = "trace-item";
      button.dataset.traceIndex = String(index);
      button.setAttribute("aria-current", String(selected));
      top.className = "trace-item-top";
      title.className = "trace-item-title";
      titleGroup.className = "trace-item-title-group";
      statusBadge.className = "trace-row-status";
      time.className = "trace-item-time";
      message.className = "trace-item-message";
      meta.className = "trace-item-meta";

      title.textContent = intentLabels[trace.intent] || trace.intent || "未知意图";
      const traceStatus = getTraceStatus(trace);
      statusBadge.textContent = traceStatus.label;
      statusBadge.dataset.tone = traceStatus.tone;
      time.textContent = formatRelativeTime(record.timestamp);
      time.dateTime = record.timestamp || "";
      message.textContent = trace.user_msg || "未记录买家消息";
      meta.append(
        makeTextSpan(trace.routed_agent || "未记录路由"),
        makeTextSpan(trace.chat_id || "无会话 ID"),
      );
      titleGroup.append(title, statusBadge);
      top.append(titleGroup, time);
      button.append(top, message, meta);
      elements.traceList.append(button);
    });

    let selectedIndex = records.findIndex((record) => record.timestamp === state.selectedTraceTimestamp);
    if (selectedIndex < 0) {
      selectedIndex = 0;
    }
    renderTraceDetail(records[selectedIndex]);
    markSelectedTrace(selectedIndex);
  }

  function selectTraceFromEvent(event) {
    const button = event.target.closest("button[data-trace-index]");
    if (!button) {
      return;
    }
    const index = Number(button.dataset.traceIndex);
    if (!Number.isInteger(index) || !state.visibleTraces[index]) {
      return;
    }
    markSelectedTrace(index);
    renderTraceDetail(state.visibleTraces[index]);
  }

  function markSelectedTrace(index) {
    const record = state.visibleTraces[index];
    state.selectedTraceTimestamp = record ? record.timestamp : null;
    elements.traceList.querySelectorAll(".trace-item").forEach((item, itemIndex) => {
      item.setAttribute("aria-current", String(itemIndex === index));
    });
  }

  function getTraceStatus(trace) {
    const ruleViolations = trace.rules && Array.isArray(trace.rules.violations) ? trace.rules.violations : [];
    const styleViolations = trace.style && Array.isArray(trace.style.unresolved_violations)
      ? trace.style.unresolved_violations
      : [];
    if (trace.no_reply === true) {
      return { label: "已拦截", tone: "warning", key: "blocked" };
    }
    if ((trace.rules && trace.rules.safe === false) || (trace.style && trace.style.safe === false)
      || ruleViolations.length > 0 || styleViolations.length > 0) {
      return { label: "需复核", tone: "warning", key: "review" };
    }
    return { label: "已通过", tone: "ok", key: "safe" };
  }

  function renderDashboardInsights() {
    const records = state.traces;
    const statuses = records.map((record) => getTraceStatus(record && record.trace ? record.trace : {}));
    const safeCount = statuses.filter((status) => status.key === "safe").length;
    const attentionCount = statuses.length - safeCount;
    const safeRate = records.length ? Math.round((safeCount / records.length) * 100) : 0;
    const rateValue = elements.dashboardSafeRate.querySelector("strong");

    elements.dashboardSafeRate.style.setProperty("--score", String(safeRate));
    rateValue.textContent = `${safeRate}%`;
    elements.dashboardSafeRateNote.textContent = records.length
      ? `${safeCount} 条通过，${attentionCount} 条需要关注`
      : state.traceErrorIsAuth ? "设置访问令牌后显示质量统计" : "完成一次回复试跑后开始统计";

    renderIntentDistribution(records);
    renderDashboardTraceTable(records.slice(0, 6));
    renderDashboardActivity(records.slice(0, 4));
    renderDashboardFocus();
  }

  function renderIntentDistribution(records) {
    const counts = { price: 0, tech: 0, default: 0 };
    records.forEach((record) => {
      const intent = record && record.trace ? record.trace.intent : "";
      if (Object.prototype.hasOwnProperty.call(counts, intent)) {
        counts[intent] += 1;
      }
    });
    const maxCount = Math.max(1, ...Object.values(counts));
    elements.dashboardIntentBars.replaceChildren();

    Object.entries(counts).forEach(([intent, count]) => {
      const row = document.createElement("div");
      const label = document.createElement("span");
      const track = document.createElement("span");
      const bar = document.createElement("i");
      const value = document.createElement("strong");
      row.className = "intent-row";
      track.className = "intent-track";
      label.textContent = intentLabels[intent] || intent;
      bar.style.width = `${Math.round((count / maxCount) * 100)}%`;
      value.textContent = String(count);
      track.append(bar);
      row.append(label, track, value);
      elements.dashboardIntentBars.append(row);
    });
  }

  function renderDashboardTraceTable(records) {
    elements.dashboardTraceTable.replaceChildren();
    if (records.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 5;
      cell.className = "table-empty";
      cell.textContent = state.traceErrorIsAuth ? "Trace 已启用访问保护" : "还没有可展示的 Agent 决策";
      row.append(cell);
      elements.dashboardTraceTable.append(row);
      return;
    }

    records.forEach((record, index) => {
      const trace = record && record.trace ? record.trace : {};
      const status = getTraceStatus(trace);
      const row = document.createElement("tr");
      const statusCell = document.createElement("td");
      const statusBadge = document.createElement("span");
      const messageCell = document.createElement("td");
      const messageButton = document.createElement("button");
      const intentCell = document.createElement("td");
      const agentCell = document.createElement("td");
      const timeCell = document.createElement("td");
      const time = document.createElement("time");

      statusBadge.className = "table-status";
      statusBadge.dataset.tone = status.tone;
      statusBadge.textContent = status.label;
      messageButton.type = "button";
      messageButton.className = "table-message";
      messageButton.dataset.dashboardTraceIndex = String(index);
      messageButton.textContent = trace.user_msg || "未记录买家消息";
      messageButton.title = messageButton.textContent;
      intentCell.textContent = intentLabels[trace.intent] || trace.intent || "未知";
      agentCell.textContent = trace.routed_agent || "未记录";
      time.textContent = formatRelativeTime(record.timestamp);
      time.dateTime = record.timestamp || "";
      statusCell.append(statusBadge);
      messageCell.append(messageButton);
      timeCell.append(time);
      row.append(statusCell, messageCell, intentCell, agentCell, timeCell);
      elements.dashboardTraceTable.append(row);
    });
  }

  function renderDashboardActivity(records) {
    elements.dashboardActivityList.replaceChildren();
    const overview = state.overview || {};
    const worker = overview.worker || {};
    const workerSnapshot = worker.status && typeof worker.status === "object" ? worker.status : {};
    const entries = [];

    if (state.overview && !worker.healthy) {
      entries.push({
        title: workerSnapshot.last_error_type === "XianyuRiskControlError" ? "平台风控阻断 Worker" : "Worker 需要处理",
        detail: reasonLabels[worker.reason] || humanizeKey(worker.reason || "unknown"),
        timestamp: workerSnapshot.updated_at,
        tone: "warning",
      });
    }
    records.forEach((record) => {
      const trace = record && record.trace ? record.trace : {};
      const status = getTraceStatus(trace);
      entries.push({
        title: `${intentLabels[trace.intent] || trace.intent || "未知意图"} · ${status.label}`,
        detail: trace.user_msg || "未记录买家消息",
        timestamp: record.timestamp,
        tone: status.tone,
      });
    });

    if (entries.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state compact-empty";
      empty.append(makeParagraph(state.traceErrorIsAuth ? "输入访问令牌后显示实时动态。" : "新的 Agent 决策会出现在这里。"));
      elements.dashboardActivityList.append(empty);
      return;
    }

    entries.slice(0, 4).forEach((entry) => {
      const item = document.createElement("article");
      const dot = document.createElement("span");
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      const detail = document.createElement("p");
      const time = document.createElement("time");
      item.className = "activity-item";
      dot.className = "activity-dot";
      dot.dataset.tone = entry.tone;
      title.textContent = entry.title;
      detail.textContent = entry.detail;
      time.textContent = entry.timestamp ? formatRelativeTime(entry.timestamp) : "刚刚";
      time.dateTime = entry.timestamp || "";
      copy.append(title, detail);
      item.append(dot, copy, time);
      elements.dashboardActivityList.append(item);
    });
  }

  function renderDashboardFocus() {
    const overview = state.overview;
    if (!overview) {
      elements.dashboardFocusStatus.textContent = "API 离线";
      elements.dashboardFocusStatus.dataset.tone = "error";
      elements.dashboardFocusTitle.textContent = "操作台无法读取真实运行状态";
      elements.dashboardFocusMessage.textContent = "先启动本地 API，再刷新页面读取 Worker 与 Trace。";
      return;
    }

    const worker = overview.worker || {};
    const workerSnapshot = worker.status && typeof worker.status === "object" ? worker.status : {};
    if (workerSnapshot.last_error_type === "XianyuRiskControlError") {
      elements.dashboardFocusStatus.textContent = "平台风控";
      elements.dashboardFocusStatus.dataset.tone = "error";
      elements.dashboardFocusTitle.textContent = "闲鱼风控验证仍在阻断 Worker";
      elements.dashboardFocusMessage.textContent = "保持 Dry-run，完成官方验证并更新登录态后，再重启 Worker。";
    } else if (!worker.healthy) {
      elements.dashboardFocusStatus.textContent = "需要处理";
      elements.dashboardFocusStatus.dataset.tone = "warning";
      elements.dashboardFocusTitle.textContent = "Worker 当前不能视为可用";
      elements.dashboardFocusMessage.textContent = reasonLabels[worker.reason] || humanizeKey(worker.reason || "unknown");
    } else if (workerSnapshot.dry_run === false) {
      elements.dashboardFocusStatus.textContent = "真实发送";
      elements.dashboardFocusStatus.dataset.tone = "warning";
      elements.dashboardFocusTitle.textContent = "在线 Worker 已开启真实发送";
      elements.dashboardFocusMessage.textContent = "请持续检查 Trace、价格护栏和账号状态，回复试跑页仍不会触达买家。";
    } else {
      elements.dashboardFocusStatus.textContent = "安全运行";
      elements.dashboardFocusStatus.dataset.tone = "ok";
      elements.dashboardFocusTitle.textContent = "Worker 与本地安全模式运行正常";
      elements.dashboardFocusMessage.textContent = "可以继续通过回复试跑验证新场景，再根据 Trace 评估是否调整规则。";
    }
  }

  function selectDashboardTrace(event) {
    const button = event.target.closest("button[data-dashboard-trace-index]");
    if (!button) {
      return;
    }
    const record = state.traces[Number(button.dataset.dashboardTraceIndex)];
    if (!record) {
      return;
    }
    elements.traceSearch.value = "";
    elements.traceIntentFilter.value = "";
    elements.traceStatusFilter.value = "";
    state.selectedTraceTimestamp = record.timestamp;
    applyTraceFilters();
    activateView("traces", { updateHash: true, focus: true });
  }

  function renderTraceError(error, options) {
    const settings = { promptAuth: true, ...(options || {}) };
    state.visibleTraces = [];
    elements.traceList.replaceChildren();
    elements.traceEmpty.hidden = true;
    elements.traceError.hidden = false;
    elements.traceCount.textContent = "读取失败";
    elements.traceFilterSummary.textContent = "Trace 读取失败";
    elements.sidebarTraceCount.textContent = "读取失败";
    state.traceErrorIsAuth = error instanceof ApiError && error.status === 401;

    if (state.traceErrorIsAuth) {
      elements.traceErrorTitle.textContent = "需要访问令牌";
      elements.traceErrorMessage.textContent = "输入有效的 Bearer token 后即可读取 Trace。";
      elements.traceErrorAction.textContent = "输入令牌";
      state.retryAfterToken = () => loadTraces(true);
      if (settings.promptAuth) {
        showTokenDialog("访问 Trace 需要有效令牌。");
      }
    } else {
      elements.traceErrorTitle.textContent = "无法读取 Trace";
      elements.traceErrorMessage.textContent = describeGenericError(error);
      elements.traceErrorAction.textContent = "重试";
    }
    clearTraceDetail();
    renderDashboardInsights();
  }

  function clearTraceDetail() {
    elements.traceDetailContent.hidden = true;
    elements.traceDetailEmpty.hidden = false;
    state.selectedTraceTimestamp = null;
  }

  function renderTraceDetail(record) {
    const trace = record && record.trace ? record.trace : {};
    elements.traceDetailEmpty.hidden = true;
    elements.traceDetailContent.hidden = false;
    elements.traceDetailTime.textContent = formatDateTime(record.timestamp);
    elements.traceDetailIntent.textContent = intentLabels[trace.intent] || trace.intent || "未知意图";
    elements.traceDetailIntent.dataset.tone = trace.no_reply ? "warning" : "neutral";
    elements.traceDetailMessage.textContent = trace.user_msg || "未记录买家消息正文";
    elements.traceSections.replaceChildren();

    appendTraceSection("决策摘要", {
      "路由 Agent": trace.routed_agent || "未记录",
      "会话 ID": trace.chat_id || "未记录",
      "议价次数": trace.bargain_count ?? 0,
      "跳过回复": trace.no_reply === true ? "是" : "否",
    });
    appendTraceSection("护栏", Array.isArray(trace.guardrails) ? trace.guardrails : []);
    appendTraceSection("价格决策", trace.price_decision || {}, priceLabels);
    appendTraceSection("知识命中", trace.knowledge || {}, knowledgeLabels);
    appendTraceSection("模型状态", trace.model || {});
    appendTraceSection("规则与表达", {
      rules: trace.rules || {},
      style: trace.style || {},
    });
    appendTraceSection("阶段耗时", trace.timings_ms || {}, {}, "ms");
    elements.rawTraceOutput.textContent = JSON.stringify(record, null, 2);
  }

  function appendTraceSection(title, value, labels, suffix) {
    const section = document.createElement("section");
    const heading = document.createElement("h4");
    section.className = "trace-section";
    heading.textContent = title;
    section.append(heading);

    if (Array.isArray(value)) {
      if (value.length === 0) {
        section.append(makeParagraph("未触发"));
      } else {
        section.append(makeChipList(value));
      }
    } else if (value && typeof value === "object" && Object.keys(value).length > 0) {
      const grid = document.createElement("div");
      grid.className = "trace-section-grid";
      Object.entries(value).forEach(([key, entry]) => {
        const pair = document.createElement("div");
        const label = document.createElement("p");
        const content = document.createElement("p");
        label.className = "metric-label";
        label.textContent = labels && labels[key] ? labels[key] : humanizeKey(key);
        content.textContent = `${formatValue(entry)}${suffix && typeof entry === "number" ? suffix : ""}`;
        pair.append(label, content);
        grid.append(pair);
      });
      section.append(grid);
    } else {
      section.append(makeParagraph("未记录"));
    }
    elements.traceSections.append(section);
  }

  async function submitReply(event) {
    event.preventDefault();
    clearReplyFeedback();
    clearAllFieldErrors();

    const payload = buildReplyPayload();
    if (!payload) {
      return;
    }

    setReplyLoading(true);
    try {
      const response = await apiFetch("/api/reply", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.latestReply = response;
      renderReply(response);
      showNotice("模拟回复已生成", "结果仅显示在本地操作台，没有发送给闲鱼买家。", "ok", 4200);
      state.selectedTraceTimestamp = null;
      await Promise.allSettled([loadTraces(false), refreshOverviewOnly()]);
    } catch (error) {
      handleReplyError(error);
    } finally {
      setReplyLoading(false);
    }
  }

  function buildReplyPayload() {
    const userMessage = elements.userMessage.value.trim();
    if (!userMessage) {
      setFieldError(elements.userMessage, elements.userMessageError, "请输入买家消息。");
      elements.userMessage.focus();
      return null;
    }

    if (!elements.replyForm.reportValidity()) {
      showReplyFeedback("请检查必填项和字段格式。", "error");
      return null;
    }

    const additionalMessages = elements.additionalMessages.value
      .split(/\r?\n/)
      .map((message) => message.trim())
      .filter(Boolean);
    if (additionalMessages.length > 10) {
      showReplyFeedback("连续消息最多 10 条，请删减后重试。", "error");
      elements.additionalMessages.focus();
      return null;
    }
    if (additionalMessages.some((message) => message.length > 1000)) {
      showReplyFeedback("每条连续消息最多 1000 字。", "error");
      elements.additionalMessages.focus();
      return null;
    }

    const requestId = elements.requestId.value.trim();
    if (requestId && !/^[A-Za-z0-9._:-]{1,128}$/.test(requestId)) {
      showReplyFeedback("请求 ID 只能包含字母、数字、点、下划线、冒号和短横线。", "error");
      elements.requestId.focus();
      return null;
    }

    const itemInfo = parseJsonField(elements.itemInfo, elements.itemInfoError, "商品信息", "object");
    if (itemInfo === PARSE_ERROR) {
      return null;
    }
    const context = parseJsonField(elements.conversationContext, elements.contextError, "对话上下文", "array");
    if (context === PARSE_ERROR) {
      return null;
    }

    const payload = {
      user_msg: userMessage,
      additional_user_msgs: additionalMessages,
      chat_id: elements.chatId.value.trim(),
      item_id: elements.itemId.value.trim(),
      user_id: elements.userId.value.trim(),
      assistant_id: elements.assistantId.value.trim(),
      persist_turn: elements.persistTurn.checked,
    };
    if (requestId) {
      payload.request_id = requestId;
    }
    if (itemInfo !== null) {
      payload.item_info = itemInfo;
    }
    if (context !== null) {
      payload.context = context;
    }
    return payload;
  }

  const PARSE_ERROR = Symbol("parse-error");

  function parseJsonField(input, errorElement, label, expectedType) {
    const raw = input.value.trim();
    if (!raw) {
      return null;
    }
    try {
      const value = JSON.parse(raw);
      const valid = expectedType === "array"
        ? Array.isArray(value)
        : value !== null && typeof value === "object" && !Array.isArray(value);
      if (!valid) {
        throw new TypeError(`${label}必须是${expectedType === "array" ? "数组" : "对象"}。`);
      }
      return value;
    } catch (error) {
      const message = error instanceof SyntaxError
        ? `${label}不是有效的 JSON：${error.message}`
        : error.message;
      setFieldError(input, errorElement, message);
      input.focus();
      return PARSE_ERROR;
    }
  }

  function renderReply(response) {
    const trace = response.trace && typeof response.trace === "object" ? response.trace : {};
    const memory = response.memory && typeof response.memory === "object" ? response.memory : {};
    elements.resultEmpty.hidden = true;
    elements.resultLoading.hidden = true;
    elements.resultContent.hidden = false;
    elements.copyReplyButton.hidden = false;
    elements.openLatestTraceButton.hidden = false;
    elements.replyOutput.textContent = response.reply === "-" ? "本轮无需回复" : response.reply || "未返回回复内容";
    elements.resultBadges.replaceChildren(
      makeBadge(intentLabels[response.intent] || response.intent || "未知意图", "neutral"),
      makeBadge(trace.routed_agent || "未记录路由", "neutral"),
      trace.no_reply ? makeBadge("跳过回复", "warning") : makeBadge("已生成", "ok"),
    );

    elements.replayNote.hidden = !response.idempotent_replay;
    elements.replayNote.textContent = response.idempotent_replay
      ? `请求 ${response.request_id || ""} 命中幂等回放，没有重复写入 Trace 或记忆。`
      : "";

    renderDataList(elements.decisionOutput, {
      "识别意图": intentLabels[response.intent] || response.intent || "未知",
      "路由 Agent": trace.routed_agent || "未记录",
      "是否跳过": trace.no_reply ? "是" : "否",
      "触发护栏": Array.isArray(trace.guardrails) && trace.guardrails.length ? trace.guardrails.join("、") : "未触发",
    });
    renderObjectResult(elements.priceOutput, trace.price_decision, priceLabels, "本轮没有价格决策。");
    renderObjectResult(elements.knowledgeOutput, trace.knowledge, knowledgeLabels, "本轮没有知识命中记录。");
    renderMemory(memory);
    elements.rawReplyOutput.textContent = JSON.stringify(response, null, 2);
  }

  function renderObjectResult(container, value, labels, emptyText) {
    container.replaceChildren();
    if (!value || typeof value !== "object" || Object.keys(value).length === 0) {
      const empty = makeParagraph(emptyText);
      empty.className = "empty-inline";
      container.append(empty);
      return;
    }
    const list = document.createElement("dl");
    list.className = "data-list";
    Object.entries(value).forEach(([key, entry]) => appendDataPair(list, labels[key] || humanizeKey(key), formatValue(entry)));
    container.append(list);
  }

  function renderMemory(memory) {
    elements.memoryOutput.replaceChildren();
    const list = document.createElement("dl");
    list.className = "data-list";
    appendDataPair(list, "会话 ID", memory.chat_id || "未记录");
    appendDataPair(list, "议价次数", formatValue(memory.bargain_count ?? 0));
    appendDataPair(list, "买家最高出价", formatPrice(memory.buyer_highest_offer));
    appendDataPair(list, "已承诺最低价", formatPrice(memory.lowest_price_committed));
    elements.memoryOutput.append(list);

    const messages = Array.isArray(memory.messages) ? memory.messages.slice(-6) : [];
    if (messages.length === 0) {
      const empty = makeParagraph("当前会话没有本地记忆。未勾选写入时，这是预期状态。");
      empty.className = "empty-inline";
      elements.memoryOutput.append(empty);
      return;
    }

    const messageList = document.createElement("ul");
    messageList.className = "memory-messages";
    messages.forEach((message) => {
      const item = document.createElement("li");
      const role = document.createElement("span");
      const content = document.createElement("span");
      item.className = "memory-message";
      role.className = "memory-role";
      role.textContent = message.role === "assistant" ? "卖家" : message.role === "user" ? "买家" : message.role || "记录";
      content.textContent = message.content || "";
      item.append(role, content);
      messageList.append(item);
    });
    elements.memoryOutput.append(messageList);
  }

  function handleReplyError(error) {
    elements.resultLoading.hidden = true;
    if (!state.latestReply) {
      elements.resultEmpty.hidden = false;
    }

    if (error instanceof ApiError && error.status === 401) {
      showReplyFeedback("访问令牌缺失或无效。保存有效令牌后会自动重试本次模拟。", "error");
      state.retryAfterToken = () => elements.replyForm.requestSubmit();
      showTokenDialog("模拟回复需要有效的访问令牌。");
      return;
    }

    if (error instanceof ApiError && error.status === 409) {
      const detail = error.payload && error.payload.detail;
      const message = detail === "request_id_payload_mismatch"
        ? "这个请求 ID 已用于另一组内容。请生成新的请求 ID 后再试。"
        : "这个请求 ID 正在处理中。请稍后用相同内容重试。";
      showReplyFeedback(message, "warning", detail === "request_id_payload_mismatch" ? {
        label: "生成新请求 ID",
        handler: () => {
          generateRequestId();
          clearReplyFeedback();
          elements.requestId.focus();
        },
      } : null);
      return;
    }

    if (error instanceof ApiError && error.status === 422) {
      const details = error.payload && Array.isArray(error.payload.detail) ? error.payload.detail : [];
      const messages = details.length
        ? details.map((detail) => {
          const path = Array.isArray(detail.loc) ? detail.loc.filter((part) => part !== "body") : [];
          const field = path.length ? fieldLabels[path[0]] || String(path.join(".")) : "请求内容";
          return `${field}：${translateValidationMessage(detail.msg || "格式不正确")}`;
        })
        : ["请求字段未通过服务端校验。"];
      showReplyValidationErrors(messages);
      return;
    }

    const requestSuffix = error instanceof ApiError && error.requestId ? ` 请求编号：${error.requestId}` : "";
    showReplyFeedback(`${describeGenericError(error)}${requestSuffix}`, "error");
  }

  function showReplyValidationErrors(messages) {
    elements.replyFeedback.replaceChildren();
    const title = document.createElement("strong");
    const list = document.createElement("ul");
    title.textContent = "部分字段需要修改";
    messages.forEach((message) => {
      const item = document.createElement("li");
      item.textContent = message;
      list.append(item);
    });
    elements.replyFeedback.append(title, list);
    elements.replyFeedback.dataset.tone = "error";
    elements.replyFeedback.hidden = false;
    elements.replyFeedback.focus?.();
  }

  function showReplyFeedback(message, tone, action) {
    elements.replyFeedback.replaceChildren();
    const text = document.createElement("p");
    text.textContent = message;
    elements.replyFeedback.append(text);
    if (action) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button button-secondary button-compact";
      button.textContent = action.label;
      button.addEventListener("click", action.handler, { once: true });
      elements.replyFeedback.append(button);
    }
    elements.replyFeedback.dataset.tone = tone || "error";
    elements.replyFeedback.hidden = false;
  }

  function clearReplyFeedback() {
    elements.replyFeedback.hidden = true;
    elements.replyFeedback.replaceChildren();
    delete elements.replyFeedback.dataset.tone;
  }

  function setReplyLoading(loading) {
    elements.submitReplyButton.disabled = loading;
    elements.submitReplyButton.querySelector(".button-label").hidden = loading;
    elements.submitReplyButton.querySelector(".button-loading").hidden = !loading;
    elements.resultContent.hidden = loading || !state.latestReply;
    elements.resultEmpty.hidden = loading || Boolean(state.latestReply);
    elements.resultLoading.hidden = !loading;
    elements.resultLoading.setAttribute("aria-hidden", String(!loading));
    elements.copyReplyButton.hidden = loading || !state.latestReply;
    elements.openLatestTraceButton.hidden = loading || !state.latestReply;
    document.querySelector(".result-panel").setAttribute("aria-busy", String(loading));
  }

  function resetReplyView() {
    state.latestReply = null;
    elements.resultContent.hidden = true;
    elements.resultLoading.hidden = true;
    elements.resultEmpty.hidden = false;
    elements.copyReplyButton.hidden = true;
    elements.openLatestTraceButton.hidden = true;
    clearReplyFeedback();
    clearAllFieldErrors();
    updateMessageCount();
    generateRequestId();
  }

  async function refreshOverviewOnly() {
    try {
      const overview = await apiFetch("/api/overview");
      state.overview = overview;
      renderOverview(overview);
    } catch (error) {
      showNotice("回复已生成，但总览刷新失败", describeGenericError(error), "warning");
    }
  }

  function showTokenDialog(message) {
    elements.accessToken.value = getToken();
    elements.showToken.checked = false;
    elements.accessToken.type = "password";
    elements.tokenDialogStatus.textContent = message || tokenPolicyText();
    if (!elements.tokenDialog.open) {
      elements.tokenDialog.showModal();
    }
    window.setTimeout(() => elements.accessToken.focus(), 0);
  }

  function closeTokenDialog() {
    if (elements.tokenDialog.open) {
      elements.tokenDialog.close();
    }
  }

  async function saveToken(event) {
    event.preventDefault();
    const token = elements.accessToken.value.trim();
    if (state.access.tokenRequired && !token) {
      elements.tokenDialogStatus.textContent = "当前 API 要求令牌，请输入后保存。";
      elements.accessToken.focus();
      return;
    }
    try {
      if (token) {
        sessionStorage.setItem(TOKEN_KEY, token);
      } else {
        sessionStorage.removeItem(TOKEN_KEY);
      }
    } catch (error) {
      elements.tokenDialogStatus.textContent = "浏览器拒绝保存会话令牌，请检查隐私设置。";
      return;
    }
    updateTokenIndicator();
    closeTokenDialog();
    showNotice("访问令牌已更新", token ? "令牌仅在当前标签页会话内有效。" : "当前会话未保存令牌。", "ok", 3200);

    const retry = state.retryAfterToken;
    state.retryAfterToken = null;
    if (retry) {
      await Promise.resolve(retry()).catch(() => {});
    } else {
      await loadTraces(true).catch(() => {});
    }
  }

  function clearToken() {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch (error) {
      elements.tokenDialogStatus.textContent = "浏览器拒绝修改会话存储。";
      return;
    }
    elements.accessToken.value = "";
    state.retryAfterToken = null;
    updateTokenIndicator();
    elements.tokenDialogStatus.textContent = state.access.tokenRequired
      ? "令牌已移除。当前 API 仍要求令牌。"
      : "令牌已从当前会话移除。";
  }

  function updateTokenIndicator() {
    const hasToken = Boolean(getToken());
    elements.tokenIndicator.dataset.active = String(hasToken);
    elements.openTokenButton.setAttribute(
      "aria-label",
      hasToken ? "访问令牌，当前会话已设置" : "访问令牌，当前会话未设置",
    );
  }

  function tokenPolicyText() {
    if (state.access.tokenRequired) {
      return getToken() ? "当前 API 要求令牌，本会话已设置。" : "当前 API 要求令牌，本会话尚未设置。";
    }
    return "当前 API 未强制要求令牌，也可以预先设置。";
  }

  function getToken() {
    try {
      return sessionStorage.getItem(TOKEN_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  async function apiFetch(path, options) {
    const requestOptions = { ...(options || {}) };
    const headers = new Headers(requestOptions.headers || {});
    headers.set("Accept", "application/json");
    const token = getToken();
    if (token && path !== "/api/access") {
      headers.set("Authorization", `Bearer ${token}`);
    }
    if (requestOptions.body) {
      headers.set("Content-Type", "application/json");
    }
    requestOptions.headers = headers;

    let response;
    try {
      response = await fetch(path, requestOptions);
    } catch (error) {
      throw new Error("无法连接本地 API，请确认服务已启动。", { cause: error });
    }

    const contentType = response.headers.get("content-type") || "";
    let payload = null;
    if (contentType.includes("application/json")) {
      try {
        payload = await response.json();
      } catch (error) {
        payload = null;
      }
    } else {
      const text = await response.text();
      payload = text ? { detail: text } : null;
    }

    if (!response.ok) {
      throw new ApiError(response.status, payload, response.headers.get("X-Request-ID"));
    }
    return payload || {};
  }

  function setStatus(element, tone, value) {
    element.dataset.tone = tone;
    element.querySelector(".status-value").textContent = value;
  }

  function setMetric(element, value) {
    element.classList.remove("skeleton-text");
    element.textContent = value;
  }

  function setButtonBusy(button, busy, busyLabel) {
    const iconOnly = button.classList.contains("icon-button");
    if (busy) {
      if (iconOnly) {
        button.dataset.originalAriaLabel = button.getAttribute("aria-label") || "";
        button.dataset.originalTitle = button.getAttribute("title") || "";
        button.setAttribute("aria-label", busyLabel || "处理中");
        button.setAttribute("title", busyLabel || "处理中");
        button.classList.add("is-busy");
        button.disabled = true;
        return;
      }
      button.dataset.originalLabel = button.textContent.trim();
      button.textContent = busyLabel || "处理中…";
      button.disabled = true;
    } else {
      if (iconOnly) {
        button.setAttribute("aria-label", button.dataset.originalAriaLabel || button.getAttribute("aria-label") || "");
        button.setAttribute("title", button.dataset.originalTitle || button.getAttribute("title") || "");
        button.classList.remove("is-busy");
        button.disabled = false;
        delete button.dataset.originalAriaLabel;
        delete button.dataset.originalTitle;
        return;
      }
      button.textContent = button.dataset.originalLabel || button.textContent;
      button.disabled = false;
      delete button.dataset.originalLabel;
    }
  }

  function setFieldError(input, errorElement, message) {
    input.setAttribute("aria-invalid", "true");
    errorElement.textContent = message;
    errorElement.hidden = false;
  }

  function clearFieldError(input, errorElement) {
    input.removeAttribute("aria-invalid");
    errorElement.textContent = "";
    errorElement.hidden = true;
  }

  function clearAllFieldErrors() {
    clearFieldError(elements.userMessage, elements.userMessageError);
    clearFieldError(elements.itemInfo, elements.itemInfoError);
    clearFieldError(elements.conversationContext, elements.contextError);
  }

  function updateMessageCount() {
    elements.userMessageCount.textContent = `${elements.userMessage.value.length} / 2000`;
  }

  function generateRequestId() {
    const unique = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    elements.requestId.value = `console-${unique}`;
  }

  async function copyReply() {
    if (!state.latestReply || !state.latestReply.reply) {
      return;
    }
    try {
      await copyText(state.latestReply.reply);
      const original = elements.copyReplyButton.textContent;
      elements.copyReplyButton.textContent = "已复制";
      window.setTimeout(() => {
        elements.copyReplyButton.textContent = original;
      }, 1800);
    } catch (error) {
      showNotice("复制失败", "浏览器未允许读取剪贴板，请手动选择回复文本。", "error");
    }
  }

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) {
      throw new Error("copy_failed");
    }
  }

  function renderDataList(container, values) {
    container.replaceChildren();
    Object.entries(values).forEach(([label, value]) => appendDataPair(container, label, formatValue(value)));
  }

  function appendDataPair(list, label, value) {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    wrapper.className = "data-pair";
    term.textContent = label;
    description.textContent = value;
    wrapper.append(term, description);
    list.append(wrapper);
  }

  function makeBadge(text, tone) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = text;
    badge.dataset.tone = tone || "neutral";
    return badge;
  }

  function makeChipList(values) {
    const list = document.createElement("ul");
    list.className = "chip-list";
    values.forEach((value) => {
      const item = document.createElement("li");
      item.className = "chip";
      item.textContent = formatValue(value);
      list.append(item);
    });
    return list;
  }

  function makeTextSpan(text) {
    const span = document.createElement("span");
    span.textContent = text;
    return span;
  }

  function makeParagraph(text) {
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    return paragraph;
  }

  function formatValue(value) {
    if (value === null || value === undefined || value === "") {
      return "未记录";
    }
    if (typeof value === "boolean") {
      return value ? "是" : "否";
    }
    if (typeof value === "number") {
      return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
    }
    if (Array.isArray(value)) {
      return value.length ? value.map(formatValue).join("、") : "无";
    }
    if (typeof value === "object") {
      return Object.keys(value).length ? JSON.stringify(value, null, 0) : "无";
    }
    return String(value);
  }

  function formatPrice(value) {
    if (value === null || value === undefined || value === "") {
      return "未记录";
    }
    const number = Number(value);
    return Number.isFinite(number) ? `¥${number.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}` : String(value);
  }

  function formatDateTime(value) {
    const date = toDate(value);
    if (!date) {
      return "时间未知";
    }
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(date);
  }

  function formatRelativeTime(value) {
    const date = toDate(value);
    if (!date) {
      return "时间未知";
    }
    const difference = Date.now() - date.getTime();
    if (difference < -5000) {
      return formatDateTime(value);
    }
    if (difference < 5000) {
      return "刚刚";
    }
    return `${formatDuration(difference)}前`;
  }

  function formatDuration(milliseconds) {
    const seconds = Math.max(0, Math.round(milliseconds / 1000));
    if (seconds < 60) {
      return `${seconds} 秒`;
    }
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) {
      return `${minutes} 分钟`;
    }
    const hours = Math.round(minutes / 60);
    if (hours < 24) {
      return `${hours} 小时`;
    }
    return `${Math.round(hours / 24)} 天`;
  }

  function toDate(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    let normalized = value;
    if (typeof value === "number") {
      normalized = value < 100000000000 ? value * 1000 : value;
    }
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function humanizeKey(value) {
    if (!value) {
      return "未记录";
    }
    return String(value).replaceAll("_", " ");
  }

  function translateValidationMessage(message) {
    const translations = [
      [/Field required/i, "此字段为必填项"],
      [/String should have at least 1 character/i, "不能为空"],
      [/String should have at most (\d+) characters/i, "内容超过长度限制"],
      [/Input should be a valid list/i, "应为 JSON 数组"],
      [/Input should be a valid dictionary/i, "应为 JSON 对象"],
      [/String should match pattern/i, "格式不符合要求"],
    ];
    const match = translations.find(([pattern]) => pattern.test(message));
    return match ? message.replace(match[0], match[1]) : message;
  }

  function numberOrZero(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
  }

  function describeGenericError(error) {
    if (error instanceof ApiError) {
      if (error.status === 404) {
        return "接口不存在，请确认前端与 API 版本一致。";
      }
      if (error.status >= 500) {
        return "本地 API 处理失败，请查看服务日志后重试。";
      }
      return error.message || `请求失败（${error.status}）。`;
    }
    return error && error.message ? error.message : "发生未知错误，请重试。";
  }

  let noticeTimer = null;

  function showNotice(title, message, tone, timeout) {
    window.clearTimeout(noticeTimer);
    elements.globalNoticeTitle.textContent = title;
    elements.globalNoticeMessage.textContent = message;
    elements.globalNotice.dataset.tone = tone || "neutral";
    elements.globalNotice.hidden = false;
    if (timeout) {
      noticeTimer = window.setTimeout(hideNotice, timeout);
    }
  }

  function hideNotice() {
    window.clearTimeout(noticeTimer);
    elements.globalNotice.hidden = true;
  }
})();
