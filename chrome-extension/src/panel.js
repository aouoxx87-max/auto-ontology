import {
  errorMessage,
  parseSelection,
  parseSettings,
  permissionOrigin,
} from "./api.js";

const element = (id) => document.getElementById(id);
let windowId;
let state;

element("settings-form").addEventListener("submit", saveSettings);
element("query").addEventListener("click", submitQuery);
element("copy").addEventListener("click", copyResult);
element("selection").addEventListener("input", updateCount);
element("endpoint").addEventListener("input", () => {
  element("token").value = "";
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "session" && changes[`query:${windowId}`]) {
    renderResult(changes[`query:${windowId}`].newValue);
  }
});
void initialize();

async function initialize() {
  try {
    windowId = (await chrome.windows.getCurrent()).id;
    const [{ settings }, session] = await Promise.all([
      chrome.storage.local.get("settings"),
      chrome.storage.session.get(["auth", `query:${windowId}`]),
    ]);
    if (settings) {
      element("endpoint").value = settings.endpoint;
      element("method").value = settings.method;
      element("field").value = settings.field;
      showDestination(settings);
    } else {
      element("configuration").open = true;
    }
    if (session.auth?.endpoint === settings?.endpoint)
      element("token").value = session.auth.token;
    renderResult(session[`query:${windowId}`]);
  } catch (error) {
    element("settings-status").textContent = errorMessage(error);
  }
}

async function saveSettings(event) {
  event.preventDefault();
  try {
    const settings = parseSettings({
      endpoint: element("endpoint").value,
      method: element("method").value,
      field: element("field").value,
    });
    const token = element("token").value.trim();
    if (/[\r\n]/.test(token)) throw new Error("Token 不能包含换行。");
    // 请求权限前不能 await 存储操作，否则 Chrome 无法识别此次按钮点击。
    const granted = await chrome.permissions.request({
      origins: [permissionOrigin(settings.endpoint)],
    });
    if (!granted) throw new Error("未获得接口访问权限，配置尚未保存。");
    await chrome.storage.session.set({
      auth: { endpoint: settings.endpoint, token },
    });
    await chrome.storage.local.set({ settings });
    showDestination(settings);
    element("settings-status").textContent = "配置已保存，可以查询了。";
  } catch (error) {
    element("settings-status").textContent = errorMessage(error);
  }
}

async function submitQuery() {
  try {
    const text = parseSelection(element("selection").value);
    element("result-status").textContent = "正在查询…";
    await chrome.runtime.sendMessage({ type: "query", text, windowId });
  } catch (error) {
    element("result-status").textContent = errorMessage(error);
  }
}

async function copyResult() {
  try {
    await navigator.clipboard.writeText(state.result);
    element("result-status").textContent = "结果已复制。";
  } catch {
    element("result-status").textContent = "复制失败，请手动选择结果并复制。";
  }
}

function renderResult(nextState) {
  const changedSelection = state?.id !== nextState?.id;
  state = nextState;
  if (!state) return;
  if (changedSelection) element("selection").value = state.text;
  updateCount();
  const success = state.status === "success";
  element("empty-state").hidden = true;
  element("result").hidden = !success;
  element("result").textContent = state.result;
  element("result-error").hidden = state.status !== "error";
  element("result-error").textContent = state.error;
  element("copy").disabled = !success || !state.result;
  element("result-status").textContent =
    state.status === "loading"
      ? "正在查询… 如长时间没有响应，可以再次点击查询。"
      : success
        ? `HTTP ${state.httpStatus} · ${(state.elapsedMs / 1000).toFixed(1)} 秒${state.result ? "" : " · 接口返回空内容"}`
        : "查询未完成";
}

function updateCount() {
  element("selection-count").textContent =
    `${element("selection").value.length.toLocaleString("zh-CN")} 字符`;
}

function showDestination(settings) {
  const host = new URL(settings.endpoint).host;
  element("config-label").textContent = settings.method;
  element("destination").textContent = `发送至 ${host}`;
}
