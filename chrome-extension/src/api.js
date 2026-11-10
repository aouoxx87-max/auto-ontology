export const MAX_SELECTION_LENGTH = 20000;
export const MAX_RESPONSE_BYTES = 1024 * 1024;

export function parseSettings(input) {
  if (!input || typeof input.endpoint !== "string" || !input.endpoint.trim()) {
    throw new Error("请先填写并保存接口地址。");
  }
  const url = new URL(input.endpoint.trim());
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.hash
  ) {
    throw new Error(
      "接口必须是 HTTP 或 HTTPS 地址，不能包含用户名、密码或 # 片段。",
    );
  }
  if (!["GET", "POST"].includes(input.method)) {
    throw new Error("请求方式只能是 GET 或 POST。");
  }
  if (
    typeof input.field !== "string" ||
    !/^[A-Za-z_][A-Za-z0-9_.-]{0,63}$/.test(input.field)
  ) {
    throw new Error("参数名须以英文字母或下划线开头，最多 64 个字符。");
  }
  return { endpoint: url.href, method: input.method, field: input.field };
}

export function parseSelection(text) {
  if (typeof text !== "string" || !text.trim()) {
    throw new Error("请先在飞书文档中选中文字，再右键选择“查询所选内容”。");
  }
  if (text.length > MAX_SELECTION_LENGTH) {
    throw new Error("选中内容超过 20,000 个字符，请缩小选择范围。");
  }
  return text.trim();
}

export function permissionOrigin(endpoint) {
  const url = new URL(endpoint);
  // Chrome 的域名授权不区分端口。
  return `${url.protocol}//${url.hostname}/*`;
}

export function buildRequest(settings, text, token) {
  const url = new URL(settings.endpoint);
  const options = {
    method: settings.method,
    headers: { Accept: "application/json, text/plain, */*" },
    credentials: "omit",
    redirect: "error",
    cache: "no-store",
  };
  if (token) options.headers.Authorization = `Bearer ${token}`;
  if (settings.method === "GET") {
    url.searchParams.set(settings.field, text);
  } else {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify({ [settings.field]: text });
  }
  return { url: url.href, options };
}

export async function queryApi(
  settings,
  text,
  token,
  { signal, timeoutMs = 20000, fetchImpl = fetch } = {},
) {
  const request = buildRequest(settings, text, token);
  const timeout = AbortSignal.timeout(timeoutMs);
  request.options.signal = signal
    ? AbortSignal.any([signal, timeout])
    : timeout;
  const response = await fetchImpl(request.url, request.options);
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error(
      `接口返回 HTTP ${response.status}，请检查接口地址、参数和鉴权配置。`,
    );
  }
  const body = await readLimitedBody(response);
  const contentType = response.headers.get("content-type") ?? "text/plain";
  const result =
    /\bjson\b/i.test(contentType) && body.trim()
      ? JSON.stringify(JSON.parse(body), null, 2)
      : body;
  return { result, contentType, httpStatus: response.status };
}

async function readLimitedBody(response) {
  if (Number(response.headers.get("content-length")) > MAX_RESPONSE_BYTES) {
    await response.body?.cancel();
    throw new Error("接口响应超过 1 MB，请让接口返回更精简的结果。");
  }
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let size = 0;
  let text = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_RESPONSE_BYTES) {
      await reader.cancel();
      throw new Error("接口响应超过 1 MB，请让接口返回更精简的结果。");
    }
    text += decoder.decode(value, { stream: true });
  }
  return text + decoder.decode();
}

export function errorMessage(error) {
  if (error.name === "TimeoutError") return "请求超过 20 秒，请稍后重试。";
  if (error.name === "AbortError") return "请求已取消。";
  if (error instanceof TypeError)
    return "请求失败，请检查接口地址、网络、访问权限及 HTTPS 证书。接口不能重定向。";
  if (error instanceof SyntaxError) return "接口返回的数据不是有效的 JSON。";
  return error.message || "请求失败，请稍后重试。";
}
