const API_BASE = window.PANGGUAI_API_BASE || "http://localhost:8000";
const STORAGE_KEY = "pangguai_session";
const UID_KEY = "pangguai_uid";
// 使用较新的红米 Note 机型 UA 作为默认展示。
const DEFAULT_ANDROID_UA = "Mozilla/5.0 (Linux; Android 13; 23049RAD8C) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36";
const $ = (selector) => document.querySelector(selector);

function persistSession(token, uid) {
  localStorage.setItem(STORAGE_KEY, token);
  localStorage.setItem(UID_KEY, uid);
}

function getToken() {
  return localStorage.getItem(STORAGE_KEY);
}

function getUid() {
  return localStorage.getItem(UID_KEY);
}

function clearToken() {
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem(UID_KEY);
}

function setMessage(el, text, type = "") {
  if (!el) return;
  el.textContent = text || "";
  el.className = `message${type ? " " + type : ""}`;
}

async function api(path, options = {}) {
  const token = getToken();
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    if (res.status === 401) {
      clearToken();
      redirectToLogin();
    }
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || data.message || `请求失败 (${res.status})`);
  }
  return res.json();
}

function redirectToDashboard() {
  window.location.href = "dashboard.html";
}

function redirectToLogin() {
  window.location.href = "index.html";
}

function maskPhone(phone) {
  if (!phone) return "";
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`;
}

function maskValue(val) {
  if (!val) return "";
  if (val.length <= 6) return val;
  return `${val.slice(0, 4)}…${val.slice(-3)}`;
}

function createTableListItem(name, onClick) {
  const div = document.createElement("div");
  div.className = "list-item";
  div.textContent = name;
  div.style.cursor = "pointer";
  div.onclick = () => onClick(name);
  return div;
}

function formatTimestamp(ts) {
  if (!ts) return "-";
  const date = new Date(ts > 10000000000 ? ts : ts * 1000);
  return date.toLocaleString("zh-CN", { hour12: false });
}

function renderTableData(container, rows) {
  if (!container) return;
  container.innerHTML = "";
  if (!rows || rows.length === 0) {
    container.innerHTML = `<div class="empty-state" style="padding:40px;text-align:center;color:#94a3b8;">暂无数据</div>`;
    return;
  }

  const headers = Object.keys(rows[0] || {});
  const wrapper = document.createElement("div");
  wrapper.className = "table-wrapper";
  const table = document.createElement("table");
  table.className = "data-table";

  const thead = document.createElement("thead");
  const trHead = document.createElement("tr");
  headers.forEach((key) => {
    const th = document.createElement("th");
    th.textContent = key;
    trHead.appendChild(th);
  });
  thead.appendChild(trHead);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    headers.forEach((key) => {
      const td = document.createElement("td");
      const val = row[key];
      if (key.endsWith("_at") || key.endsWith("time") || key === "timestamp") {
        td.className = "cell-time";
        td.textContent = formatTimestamp(val);
      } else if (key === "status") {
        td.className = "cell-status";
        const badgeClass = `status-${val}`;
        td.innerHTML = `<span class="badge ${badgeClass}">${val}</span>`;
      } else if (typeof val === "string" && val.length > 30) {
        td.className = "cell-truncate";
        td.textContent = val;
        td.title = val;
        td.onclick = () => alert(val);
      } else {
        td.textContent = val !== null && val !== undefined ? val : "-";
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  wrapper.appendChild(table);
  container.appendChild(wrapper);
}

function looksLikeToken(val) {
  return typeof val === "string" && /[A-Za-z0-9_-]{20,}/.test(val);
}

function extractTokenFromPayload(payload, depth = 0) {
  if (!payload || depth > 4) return null;
  if (typeof payload === "string") {
    const token = payload.trim();
    return looksLikeToken(token) ? token : null;
  }
  if (Array.isArray(payload)) {
    for (const item of payload) {
      const candidate = extractTokenFromPayload(item, depth + 1);
      if (candidate) return candidate;
    }
    return null;
  }
  if (typeof payload === "object") {
    for (const key of ["token", "accessToken", "session_token", "sessionToken"]) {
      if (looksLikeToken(payload[key])) return payload[key];
    }
    for (const value of Object.values(payload)) {
      const candidate = extractTokenFromPayload(value, depth + 1);
      if (candidate) return candidate;
    }
  }
  return null;
}

function getSafeUA(inputUA) {
  const ua = (inputUA || navigator.userAgent || "").trim();
  const lower = ua.toLowerCase();
  const isPc = lower.includes("windows") || lower.includes("macintosh") || lower.includes("mac os");
  const hasAndroid = lower.includes("android");
  if (!ua || (isPc && !hasAndroid)) {
    return DEFAULT_ANDROID_UA;
  }
  return ua;
}

// Auth page
function initAuthPage() {
  if (getToken()) {
    redirectToDashboard();
    return;
  }
  const smsForm = $("#sms-login-form");
  const messageEl = $("#auth-message");
  const uaTextarea = $("#ua");
  const sendCodeBtn = $("#sendCodeBtn");
  const phoneInput = $("#phoneInput");
  const codeInput = $("#verifyInput");
  const loginBtn = $("#loginBtn");

  if (uaTextarea && !uaTextarea.value) {
    uaTextarea.value = getSafeUA();
  }

  let lastReportedToken = "";
  let waitingToken = false;
  let tokenTimer = null;

  const clearTokenWait = () => {
    waitingToken = false;
    if (tokenTimer) clearTimeout(tokenTimer);
    tokenTimer = null;
    if (loginBtn) {
      loginBtn.disabled = false;
      loginBtn.textContent = "登录并自动托管";
    }
  };

  function ensureLegacyScripts() {
    if (window.sendPostRequest && window.verifyCode) {
      return true;
    }
    setMessage(messageEl, "前端加密脚本未就绪，请稍后刷新重试", "error");
    return false;
  }

  async function handleTokenLogin(phone, token, ua, silent = false) {
    if (waitingToken) clearTokenWait();
    if (!/^1[3-9]\d{9}$/.test(phone)) {
      if (!silent) setMessage(messageEl, "手机号格式不正确", "error");
      return;
    }
    if (!token) {
      if (!silent) setMessage(messageEl, "Token 不能为空", "error");
      return;
    }
    if (!silent) setMessage(messageEl, "上报中…");
    try {
      const payload = { phone, token, ua: getSafeUA(ua || uaTextarea?.value) };
      const res = await api("/api/login", { method: "POST", body: JSON.stringify(payload) });
      persistSession(res.data.session_token, res.data.uid);
      if (!silent) {
        setMessage(messageEl, "登录成功，即将跳转", "success");
      } else {
        setMessage(messageEl, "捕获 Token 并自动托管成功", "success");
      }
      setTimeout(redirectToDashboard, 500);
    } catch (err) {
      if (!silent) {
        setMessage(messageEl, err.message, "error");
      } else {
        setMessage(messageEl, `自动上报失败：${err.message}`, "error");
      }
    }
  }

  function autoReportToken(token, source = "auto") {
    const phone = phoneInput?.value.trim();
    const ua = getSafeUA(uaTextarea?.value);
    if (!looksLikeToken(token) || !/^1[3-9]\d{9}$/.test(phone || "")) return;
    if (token === lastReportedToken) return;
    lastReportedToken = token;
    setMessage(messageEl, `捕获 Token（${source}），自动托管中…`, "success");
    handleTokenLogin(phone, token, ua, true);
  }

  function attachTokenCapture() {
    if (window.axios && !window.__PG_TOKEN_INTERCEPTOR) {
      window.__PG_TOKEN_INTERCEPTOR = true;

      window.axios.interceptors.response.use(
        (res) => {
          // 捕获 Token（成功逻辑）
          let token = null;
          if (res.data && res.data.token) token = res.data.token;
          if (res.data && res.data.data && res.data.data.token) token = res.data.data.token;
          if (token && looksLikeToken(token)) {
            autoReportToken(token, "接口自动捕获");
          }

          // 捕获业务错误（如验证码错误）
          if (res.data && res.data.code !== undefined && res.data.code !== 0) {
            const errorMsg = res.data.msg || "未知错误";
            setMessage($("#auth-message"), `验证失败: ${errorMsg}`, "error");
            const btn = $("#loginBtn");
            if (btn) {
              btn.disabled = false;
              btn.textContent = "验证码登录并托管";
            }
          }
          return res;
        },
        (error) => {
          // 捕获网络层面的错误
          const msg = error.response?.data?.msg || error.message || "网络请求异常";
          setMessage($("#auth-message"), `请求出错: ${msg}`, "error");
          const btn = $("#loginBtn");
          if (btn) {
            btn.disabled = false;
            btn.textContent = "验证码登录并托管";
          }
          return Promise.reject(error);
        },
      );
    }
  }

  sendCodeBtn?.addEventListener("click", (e) => {
    e.preventDefault();
    const phone = phoneInput?.value.trim();
    if (!/^1[3-9]\d{9}$/.test(phone || "")) {
      setMessage(messageEl, "请输入正确的手机号以发送验证码", "error");
      return;
    }
    if (!ensureLegacyScripts()) return;
    setMessage(messageEl, "验证码发送中…");
    window.sendPostRequest();
  });

  smsForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const phone = phoneInput?.value.trim();
    const code = codeInput?.value.trim();
    if (!/^1[3-9]\d{9}$/.test(phone || "")) {
      setMessage(messageEl, "手机号格式不正确", "error");
      return;
    }
    if (!code || !/^\d{4,8}$/.test(code)) {
      setMessage(messageEl, "请输入正确的验证码", "error");
      return;
    }
    if (!ensureLegacyScripts()) return;
    waitingToken = true;
    if (loginBtn) {
      loginBtn.disabled = true;
      loginBtn.textContent = "正在验证...";
    }
    setMessage(messageEl, "正在与服务器通信，请稍候...");
    tokenTimer = setTimeout(() => {
      if (waitingToken) {
        setMessage(messageEl, "请求超时或验证失败，请检查验证码后重试", "error");
        clearTokenWait();
      }
    }, 15000);
    // verifyCode 会在原脚本中完成 token 生成；axios 拦截器会负责捕获 token。
    try {
      window.verifyCode();
    } catch (err) {
      clearTokenWait();
      setMessage(messageEl, `验证码验证失败：${err.message || err}`, "error");
    }
  });

  // 暴露给 jsjiami 脚本调用
  window.reportTokenLogin = async ({ phone, token, ua }) => {
    const safeUA = getSafeUA(ua || uaTextarea?.value);
    await handleTokenLogin(phone, token, safeUA);
  };

  return { attachTokenCapture };
}

// Dashboard page
function initDashboardPage() {
  if (!getToken()) {
    redirectToLogin();
    return;
  }

  const els = {
    nick: $("#user-nick"),
    points: $("#user-points"),
    state: $("#task-state"),
    startBtn: $("#start-task"),
    stopBtn: $("#stop-task"),
    msg: $("#task-message"),
    logBox: $("#log-box"),
    wsDot: $("#ws-dot"),
    wsText: $("#ws-status-text"),
    optVideo: $("#opt-video"),
    optAlipay: $("#opt-alipay"),
    logout: $("#logout-btn"),
  };

  let pollTimer = null;

  els.logout?.addEventListener("click", () => {
    clearToken();
    redirectToLogin();
  });

  els.startBtn?.addEventListener("click", async () => {
    els.startBtn.disabled = true;
    els.startBtn.textContent = "提交中...";
    setMessage(els.msg, "");

    try {
      await api("/api/task/start", {
        method: "POST",
        body: JSON.stringify({
          video: els.optVideo?.checked,
          alipay: els.optAlipay?.checked,
        }),
      });
      startSmartPolling(true);
    } catch (err) {
      els.startBtn.disabled = false;
      els.startBtn.textContent = "🚀 开始执行任务";
      setMessage(els.msg, err.message, "error");
      if (err.message.includes("401") || err.message.includes("登录")) {
        setTimeout(() => redirectToLogin(), 1500);
      }
    }
  });

  function appendLog(text) {
    if (!els.logBox) return;
    const time = new Date().toLocaleTimeString("en-US", { hour12: false });
    const cleanText = text.replace(/^\[.*?\]\s*/, "");
    const div = document.createElement("div");
    div.className = "log-line";
    div.innerHTML = `<span class="log-time">[${time}]</span> <span>${cleanText}</span>`;
    els.logBox.appendChild(div);
    requestAnimationFrame(() => {
      els.logBox.scrollTop = els.logBox.scrollHeight;
    });
  }

  function connectLogs() {
    const uid = getUid() || "0";
    const cleanBase = API_BASE.replace(/\/$/, "");
    const wsProtocol = cleanBase.startsWith("https") ? "wss" : "ws";
    const hostPart = cleanBase.replace(/^https?:\/\//, "");
    const wsUrl = `${wsProtocol}://${hostPart}/ws/logs/${uid}`;
    let ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      els.wsDot?.classList.add("active");
      if (els.wsText) els.wsText.textContent = "已连接";
      appendLog("系统连接成功，准备接收日志...");
    };

    ws.onmessage = (evt) => appendLog(evt.data);

    ws.onclose = () => {
      els.wsDot?.classList.remove("active");
      if (els.wsText) els.wsText.textContent = "断开重连中...";
      setTimeout(connectLogs, 3000);
    };
  }

  function startSmartPolling(forceActive = false) {
    if (pollTimer) clearTimeout(pollTimer);

    const check = async () => {
      try {
        const res = await api("/api/user/status");
        updateUI(res);
        const isActive = res.task_status === "running" || res.task_status === "pending";
        const nextInterval = isActive ? 3000 : 10000;
        pollTimer = setTimeout(check, nextInterval);
      } catch (err) {
        pollTimer = setTimeout(check, 15000);
      }
    };

    check();
  }

  function updateUI(res) {
    els.nick.textContent = res.nick || "用户";
    els.points.textContent = res.integral;
    const statusMap = {
      idle: { text: "空闲", class: "" },
      pending: { text: "排队中...", class: "state-running" },
      running: { text: "执行中...", class: "state-running" },
      done: { text: "已完成", class: "state-done" },
      failed: { text: "执行失败", class: "state-failed" },
    };
    const s = statusMap[res.task_status] || { text: res.task_status, class: "" };
    els.state.textContent = s.text;
    els.state.className = `pill ${s.class}`;

    const stopBtn = els.stopBtn;
    if (res.task_status === "running" || res.task_status === "pending") {
      els.startBtn.style.display = "none";
      if (stopBtn) {
        stopBtn.style.display = "block";
        stopBtn.disabled = false;
        stopBtn.textContent = "⏹ 停止";
        stopBtn.onclick = async () => {
          if (confirm("确定要停止当前任务吗？")) {
            stopBtn.disabled = true;
            stopBtn.textContent = "停止中...";
            try {
              await api("/api/task/stop", { method: "POST" });
            } catch (err) {
              setMessage(els.msg, err.message, "error");
            }
          }
        };
      }
    } else {
      els.startBtn.style.display = "block";
      els.startBtn.disabled = false;
      els.startBtn.textContent = "🚀 开始执行任务";
      els.startBtn.style.opacity = "1";
      if (stopBtn) {
        stopBtn.style.display = "none";
        stopBtn.disabled = false;
        stopBtn.textContent = "⏹ 停止";
      }
    }
  }

  connectLogs();
  startSmartPolling();
}

// DB admin page
function initDbPage() {
  if (!getToken()) {
    redirectToLogin();
    return;
  }
  const tablesBox = $("#tables-list");
  const tableDataBox = $("#table-data");
  const msgBox = $("#db-message");
  const limitInput = $("#limit-input");
  const reloadBtn = $("#reload-table");
  const logoutBtn = $("#logout-btn");
  const titleEl = $("#table-title");

  let currentTable = null;

  logoutBtn?.addEventListener("click", () => {
    clearToken();
    redirectToLogin();
  });

  async function loadTables() {
    try {
      const res = await api("/admin/db/tables");
      tablesBox.innerHTML = "";
      res.tables.forEach((name) => {
        const item = createTableListItem(name, (selected) => {
          document.querySelectorAll(".list-item").forEach((el) => el.classList.remove("active"));
          item.classList.add("active");
          currentTable = selected;
          loadTable(selected);
        });
        if (currentTable === name) item.classList.add("active");
        tablesBox.appendChild(item);
      });
      if (res.tables.length > 0 && !currentTable) {
        const firstItem = tablesBox.querySelector(".list-item");
        if (firstItem) firstItem.classList.add("active");
        currentTable = res.tables[0];
        loadTable(currentTable);
      } else if (res.tables.length === 0) {
        setMessage(msgBox, "暂无表可显示", "warn");
      }
    } catch (err) {
      setMessage(msgBox, err.message, "error");
    }
  }

  async function loadTable(name) {
    if (!name) return;
    setMessage(msgBox, `加载表 ${name}...`);
    const limit = parseInt(limitInput?.value || "100", 10) || 100;
    try {
      const res = await api(`/admin/db/table/${encodeURIComponent(name)}?limit=${limit}`);
      titleEl.textContent = `${name}（共返回 ${res.count} 行）`;
      renderTableData(tableDataBox, res.rows);
      setMessage(msgBox, "加载成功", "success");
    } catch (err) {
      setMessage(msgBox, err.message, "error");
    }
  }

  reloadBtn?.addEventListener("click", () => {
    if (currentTable) loadTable(currentTable);
  });

  loadTables();
}

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  if (page === "auth") {
    const helpers = initAuthPage();
    helpers?.attachTokenCapture?.();
  }
  if (page === "dashboard") initDashboardPage();
  if (page === "dbadmin") initDbPage();
});
