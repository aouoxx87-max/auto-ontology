# 飞书选文查询

独立的 Chrome Manifest V3 扩展，无构建步骤、无运行时依赖，不依赖 Auto-Ontology 服务。

在飞书或 Lark 文档中选中文字，右键选择 **查询所选内容**，扩展会打开侧边栏并调用你配置的接口。也可以点击工具栏扩展图标，在侧栏粘贴文本并查询。

## 安装

1. 使用 Chrome 116 或以上版本，打开 `chrome://extensions`。
2. 开启右上角的「开发者模式」。
3. 点击「加载已解压的扩展程序」，选择本目录 `chrome-extension`。
4. 点击扩展图标打开侧栏，在「接口设置」中填写接口地址、请求方式和参数名。
5. 点击「保存并授权接口」，允许 Chrome 访问指定接口域名。

初次安装后还没有真实接口配置。保存配置后，可以对保留在侧栏的选文点击「查询」。

## 请求格式

假设接口为 `https://api.example.com/query`、参数名为 `text`，选择的内容为「营业收入」：

POST：

```http
POST /query
Content-Type: application/json

{"text":"营业收入"}
```

GET：

```text
https://api.example.com/query?text=%E8%90%A5%E4%B8%9A%E6%94%B6%E5%85%A5
```

GET 保留接口原有查询参数，但替换与选文参数同名的参数；参数名可改成 `query`、`keyword` 等。支持可选的 `Authorization: Bearer ...`。Token 仅保存在本次浏览器会话，不同步到其他设备，重启浏览器或重新加载扩展后需重填。修改接口地址时会清空 Token 输入框。

返回 `application/json`（含 `+json`）时会格式化展示；其他类型按纯文本显示，空响应也会显示成功状态。返回的 HTML 不执行，URL 作为文本显示并可复制。当前不支持复杂 JSON 请求模板、自定义签名、依赖网页登录 Cookie 的接口或流式聊天协议；提供实际接口协议后可扩展。

## 数据与权限

- 仅在点击右键查询或侧栏查询按钮时发送选中文字；不扫描全文，也不发送文档标题、文档 URL 或飞书 Cookie。
- 接口配置持久保存到当前浏览器；选文、结果和 Token 只放在 `chrome.storage.session`。每个窗口保留最近一次查询，关闭窗口会清除其查询。
- 所需权限为 `contextMenus`、`storage`、`sidePanel`。接口访问使用可选域名授权；Chrome 的域名权限不区分端口。无需飞书 OpenAPI 权限或文档访问 Token。
- 请求不携带浏览器 Cookie、不跟随重定向。每次请求最多 20 秒，选文最多 20,000 字符，响应最多 1 MB。连续查询会取消前一次请求，旧结果不会覆盖新结果。
- 默认右键入口匹配 `https://*.feishu.cn/*` 和 `https://*.larksuite.com/*`。企业自定义域名可在 `src/background.js` 的 `documentPatterns` 中添加。
- 右键入口依赖浏览器的文本选择。如果飞书某种编辑器、表格或画布不暴露原生选区，可复制内容到侧栏查询。

## 文件结构

```text
manifest.json        权限、后台进程和侧栏声明
panel.html / .css     中文侧栏界面
src/background.js    右键事件、请求调度和按窗口保存结果
src/api.js           输入校验、请求编码、超时及响应处理
src/panel.js         接口设置、授权和结果展示
tests/               HTTP 集成测试和 Chrome API 模拟测试
```

## 验证

在本目录执行 `npm test`，需要 Node.js 22 或以上版本，无须安装依赖。测试会启动临时的本地 HTTP 服务，覆盖参数编码、鉴权、权限拒绝、超时、取消、响应大小及多窗口请求竞争。

手动验收：安装后配置实际接口；在飞书文档选择一段文本并右键查询；检查接口收到的参数和侧栏结果；快速连续选择两段内容，确认只展示最新结果；关闭并重启 Chrome，确认 Token 已清空。

实现依据：[Chrome Side Panel](https://developer.chrome.com/docs/extensions/reference/api/sidePanel)、[可选权限](https://developer.chrome.com/docs/extensions/reference/api/permissions)、[跨域请求](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests)。
