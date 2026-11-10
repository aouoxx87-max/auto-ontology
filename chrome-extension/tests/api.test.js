import test, { after, before } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import {
  buildRequest,
  MAX_RESPONSE_BYTES,
  parseSelection,
  parseSettings,
  permissionOrigin,
  queryApi,
} from "../src/api.js";

let server;
let base;
before(async () => {
  server = createServer(async (req, res) => {
    if (req.url === "/error") {
      res.writeHead(401);
      res.end("secret server details");
      return;
    }
    if (req.url === "/redirect") {
      res.writeHead(302, { Location: "/echo" });
      res.end();
      return;
    }
    if (req.url === "/slow") {
      setTimeout(() => res.end("late"), 80);
      return;
    }
    if (req.url === "/html") {
      res.setHeader("Content-Type", "text/html");
      res.end('<script>alert("x")</script>');
      return;
    }
    if (req.url === "/empty") {
      res.writeHead(204);
      res.end();
      return;
    }
    if (req.url === "/invalid-json") {
      res.setHeader("Content-Type", "application/json");
      res.end("broken");
      return;
    }
    if (req.url === "/large") {
      res.writeHead(200, { "Transfer-Encoding": "chunked" });
      res.end("x".repeat(MAX_RESPONSE_BYTES + 1));
      return;
    }
    let body = "";
    for await (const chunk of req) body += chunk;
    res.setHeader("Content-Type", "application/json");
    res.end(
      JSON.stringify({
        method: req.method,
        url: req.url,
        body,
        authorization: req.headers.authorization ?? null,
      }),
    );
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  base = `http://127.0.0.1:${server.address().port}`;
});
after(async () => {
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
});

const settings = (path = "/echo", method = "POST") =>
  parseSettings({ endpoint: `${base}${path}`, method, field: "text" });

test("POST sends only selected text as JSON and attaches the explicit token", async () => {
  const result = JSON.parse(
    (await queryApi(settings(), "中文 & a=b\n下一行", "test-token")).result,
  );
  assert.equal(result.method, "POST");
  assert.deepEqual(JSON.parse(result.body), { text: "中文 & a=b\n下一行" });
  assert.equal(result.authorization, "Bearer test-token");
});

test("GET safely encodes Unicode and preserves existing query parameters", async () => {
  const result = JSON.parse(
    (
      await queryApi(
        settings("/echo?fixed=1&text=old", "GET"),
        "中文&a=b?#",
        "",
      )
    ).result,
  );
  const url = new URL(result.url, base);
  assert.equal(url.searchParams.get("text"), "中文&a=b?#");
  assert.equal(url.searchParams.get("fixed"), "1");
  assert.equal(url.searchParams.getAll("text").length, 1);
  assert.equal(result.body, "");
  assert.equal(result.authorization, null);
});

test("custom field names work without sending document URL or title", () => {
  const config = parseSettings({
    endpoint: "https://example.com/lookup",
    method: "POST",
    field: "query",
  });
  const request = buildRequest(config, "selection", "");
  assert.deepEqual(JSON.parse(request.options.body), { query: "selection" });
  assert.equal(request.options.credentials, "omit");
  assert.equal(request.options.redirect, "error");
});

test("rejects missing configuration, credentials in URLs, scripts and invalid fields", () => {
  assert.throws(() => parseSettings(undefined));
  for (const endpoint of [
    "javascript:alert(1)",
    "file:///tmp/a",
    "https://name:pass@example.com",
    "https://example.com/#secret",
    "no url",
  ]) {
    assert.throws(() =>
      parseSettings({ endpoint, method: "POST", field: "text" }),
    );
  }
  assert.throws(() =>
    parseSettings({ endpoint: base, method: "PUT", field: "text" }),
  );
  assert.throws(() =>
    parseSettings({ endpoint: base, method: "POST", field: "text[0]" }),
  );
});

test("rejects empty and excessive selections without silently truncating", () => {
  for (const value of [null, {}, "  ", "a".repeat(20001)])
    assert.throws(() => parseSelection(value));
  assert.equal(parseSelection("  中间\n保留  "), "中间\n保留");
});

test("Chrome host permission matches scheme and hostname, without ports or paths", () => {
  assert.equal(
    permissionOrigin("http://localhost:3187/lookup"),
    "http://localhost/*",
  );
  assert.equal(
    permissionOrigin("https://example.com/a?q=1"),
    "https://example.com/*",
  );
});

test("HTTP failures omit arbitrary server response bodies", async () => {
  await assert.rejects(
    queryApi(settings("/error"), "text", ""),
    (error) => /HTTP 401/.test(error.message) && !/secret/.test(error.message),
  );
});

test("does not follow endpoint redirects", async () => {
  await assert.rejects(queryApi(settings("/redirect"), "text", ""));
});

test("times out and supports cancellation", async () => {
  await assert.rejects(
    queryApi(settings("/slow"), "text", "", { timeoutMs: 10 }),
    { name: "TimeoutError" },
  );
  await assert.rejects(
    queryApi(settings("/slow"), "text", "", { signal: AbortSignal.abort() }),
    { name: "AbortError" },
  );
});

test("returns HTML as plain text and handles empty responses", async () => {
  assert.equal(
    (await queryApi(settings("/html"), "text", "")).result,
    '<script>alert("x")</script>',
  );
  assert.equal((await queryApi(settings("/empty"), "text", "")).result, "");
});

test("reports malformed JSON and limits streaming responses", async () => {
  await assert.rejects(
    queryApi(settings("/invalid-json"), "text", ""),
    SyntaxError,
  );
  await assert.rejects(queryApi(settings("/large"), "text", ""), /1 MB/);
});

test("decodes Unicode split across byte chunks", async () => {
  const bytes = new TextEncoder().encode("中文");
  const fetchImpl = async () =>
    new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(bytes.slice(0, 1));
          controller.enqueue(bytes.slice(1, 4));
          controller.enqueue(bytes.slice(4));
          controller.close();
        },
      }),
    );
  assert.equal(
    (await queryApi(settings(), "text", "", { fetchImpl })).result,
    "中文",
  );
});
