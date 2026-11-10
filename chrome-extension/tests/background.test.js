import test from "node:test";
import assert from "node:assert/strict";

async function setup(
  fetchImpl,
  { allowed = true, authEndpoint = "https://api.example.com/query" } = {},
) {
  const listeners = {};
  const session = {
    auth: { endpoint: authEndpoint, token: "only-this-endpoint" },
  };
  const events = [];
  globalThis.fetch = fetchImpl;
  globalThis.chrome = {
    runtime: {
      id: "test-extension",
      getURL: (path) => `chrome-extension://test-extension/${path}`,
      onInstalled: {
        addListener: (fn) => {
          listeners.install = fn;
        },
      },
      onMessage: {
        addListener: (fn) => {
          listeners.message = fn;
        },
      },
    },
    contextMenus: {
      removeAll: (callback) => callback(),
      create: () => {},
      onClicked: {
        addListener: (fn) => {
          listeners.click = fn;
        },
      },
    },
    action: {
      onClicked: {
        addListener: (fn) => {
          listeners.action = fn;
        },
      },
    },
    sidePanel: {
      open: async () => {
        events.push("open");
      },
    },
    permissions: { contains: async () => allowed },
    windows: {
      onRemoved: {
        addListener: (fn) => {
          listeners.close = fn;
        },
      },
    },
    storage: {
      local: {
        get: async () => {
          events.push("settings");
          return {
            settings: {
              endpoint: "https://api.example.com/query",
              method: "POST",
              field: "text",
            },
          };
        },
      },
      session: {
        get: async (key) => ({ [key]: session[key] }),
        set: async (value) => Object.assign(session, structuredClone(value)),
        remove: async (key) => {
          delete session[key];
        },
      },
    },
  };
  await import(`../src/background.js?test=${crypto.randomUUID()}`);
  return { listeners, session, events };
}

async function waitUntil(predicate) {
  const deadline = Date.now() + 2000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error("test state timeout");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

test("opens side panel before async work and sends selection with endpoint-bound token", async () => {
  let request;
  const mock = await setup(async (url, options) => {
    request = { url, options };
    return new Response("ok");
  });
  mock.listeners.click(
    { menuItemId: "query-feishu-selection", selectionText: "所选内容" },
    { windowId: 1 },
  );
  await waitUntil(() => mock.session["query:1"]?.status === "success");
  assert.equal(mock.events[0], "open");
  assert.equal(JSON.parse(request.options.body).text, "所选内容");
  assert.equal(
    request.options.headers.Authorization,
    "Bearer only-this-endpoint",
  );
});

test("permission denial prevents any network request", async () => {
  let calls = 0;
  const mock = await setup(
    async () => {
      calls++;
      return new Response("bad");
    },
    { allowed: false },
  );
  mock.listeners.click(
    { menuItemId: "query-feishu-selection", selectionText: "private" },
    { windowId: 2 },
  );
  await waitUntil(() => mock.session["query:2"]?.status === "error");
  assert.equal(calls, 0);
  assert.match(mock.session["query:2"].error, /授权/);
});

test("tokens for a different endpoint are not forwarded", async () => {
  let authorization;
  const mock = await setup(
    async (_, options) => {
      authorization = options.headers.Authorization;
      return new Response("ok");
    },
    { authEndpoint: "https://old.example.com/query" },
  );
  mock.listeners.click(
    { menuItemId: "query-feishu-selection", selectionText: "text" },
    { windowId: 1 },
  );
  await waitUntil(() => mock.session["query:1"]?.status === "success");
  assert.equal(authorization, undefined);
});

test("late results cannot overwrite a newer selection; separate windows keep separate results", async () => {
  const pending = [];
  const mock = await setup(
    (_, options) =>
      new Promise((resolve) =>
        pending.push({
          text: JSON.parse(options.body).text,
          resolve,
          signal: options.signal,
        }),
      ),
  );
  const click = (text, windowId) =>
    mock.listeners.click(
      { menuItemId: "query-feishu-selection", selectionText: text },
      { windowId },
    );
  click("first", 1);
  await waitUntil(() => pending.length === 1);
  click("second", 1);
  click("other window", 2);
  await waitUntil(() => pending.length === 3);
  assert.equal(pending[0].signal.aborted, true);
  pending[1].resolve(new Response("second result"));
  pending[2].resolve(new Response("other result"));
  await waitUntil(
    () =>
      mock.session["query:1"].status === "success" &&
      mock.session["query:2"].status === "success",
  );
  pending[0].resolve(new Response("stale result"));
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(mock.session["query:1"].result, "second result");
  assert.equal(mock.session["query:2"].result, "other result");
});

test("only extension panel messages can trigger a query", async () => {
  let calls = 0;
  const mock = await setup(async () => {
    calls++;
    return new Response("ok");
  });
  const message = { type: "query", text: "private", windowId: 1 };
  assert.equal(
    mock.listeners.message(
      message,
      { id: "test-extension", url: "https://tenant.feishu.cn/docx/test" },
      () => {},
    ),
    undefined,
  );
  assert.equal(calls, 0);
  const response = await new Promise((resolve) =>
    mock.listeners.message(
      message,
      {
        id: "test-extension",
        url: "chrome-extension://test-extension/panel.html",
      },
      resolve,
    ),
  );
  assert.deepEqual(response, { ok: true });
  assert.equal(calls, 1);
});
