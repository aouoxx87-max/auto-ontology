<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# 国际化维护说明

## 使用方式

页面右上角的语言选择器提供 **English** 和 **简体中文**。选择后刷新服务端组件数据，当前 URL、查询参数和客户端表单状态保持不变；语言 Cookie 有效期为一年。不增加语言路由前缀，因此已有书签、API、OAuth 和 MCP 回调继续使用原地址。

首次访问按浏览器语言选择；不支持的语言回退为英文。繁体中文偏好不会被当作简体中文的精确匹配。清除 `auto-ontology-locale` Cookie 后重新加载，会恢复浏览器语言协商。

## 代码入口

| 文件 | 用途 |
| --- | --- |
| `frontend/types/i18n.ts` | 语言、翻译器和插值参数类型 |
| `frontend/i18n/locale.ts` | 支持的语言、Cookie 名称、请求语言校验及协商 |
| `frontend/i18n/server.ts` | 在当前请求内读取语言，提供服务端翻译器；避免全局可变语言状态 |
| `frontend/i18n/LocaleProvider.tsx` | 客户端语言上下文、`useLocale` 和 `useTranslations` |
| `frontend/i18n/LanguageSwitcher.tsx` | Cookie 持久化和 `router.refresh()` |
| `frontend/i18n/translate.ts` | 词典选择、英文回退、命名参数插值 |
| `frontend/i18n/messages/zh-CN.json` | 简体中文词典，英文原文即消息键 |
| `frontend/common/date.ts` | 按语言格式化日期，保留显式传入的格式 |
| `frontend/components/ResultChart/scale.ts` | 图表数值、百分比、紧凑数字和币种格式 |

## 添加文案

客户端组件通过 Hook 获取翻译器，在文案定义处调用：

```tsx
const t = useTranslations();
return <button>{t('Save')}</button>;
```

服务端组件或 `generateMetadata` 使用 `await getTranslations()`。模块级常量可以存放英文消息键，在消费该常量的组件中翻译；纯函数则显式接收 `Translator`。避免模块初始化时读取语言，也不要设置全局 `dayjs.locale()`。

使用完整句子和命名参数，避免按英语语序拼接变量：

```tsx
t('Actions for {name}', { name: user.name });
```

对应词典条目：

```json
{
  "Actions for {name}": "{name} 的操作"
}
```

英文直接使用源消息；中文缺失的条目也会回退至源消息。插值仅替换参数，不执行 HTML，不递归替换参数值。React 负责正常的文本转义。

复数需要按数量选择完整消息，例如 `'{count} item to tag'` 和 `'{count} items to tag'`。本实现支持当前两种语言所需的命名参数及显式复数分支；如新增复杂复数语言，应引入统一的复数规则后再扩展词典。

不要在 `Text`、`Table`、结果渲染器等通用组件中无差别翻译传入字符串，否则名为 `Settings` 的业务对象可能被误改为“设置”。业务名称只作为插值参数或普通内容传递。

数字紧凑格式在中文中使用“万／亿”，英文沿用 K／M／B。币种继续使用图表原有的 USD 语义；切换语言不意味着货币换算。默认日期跟随语言，文件名等显式机器格式保持不变，时区行为沿用应用原有实现。

## 添加语言

1. 扩展 `Locale`、`LOCALE_NAMES`、`isLocale` 及 `resolveLocale` 的语言匹配规则。
2. 在 `messages` 中新增词典，并在 `createTranslator` 使用的词典表中注册。
3. 补充该语言的日期、数字和复数规则。
4. 添加请求协商、渲染和插值测试，检查完整页面及窄屏布局。

## 验证

在 `frontend` 中运行：

```bash
pnpm test
pnpm exec tsc --noEmit
pnpm format:check
pnpm lint
pnpm build
```

测试覆盖语言协商、非法 Cookie、质量权重、跨请求隔离、翻译参数完整性、词典覆盖、中文与英文首屏、权限导航，以及不应翻译的业务数据。生产构建使用项目现有的 `next/font/google`，首次构建需要能够获取 Google 字体。

手动验收：在登录页切换两种语言并刷新；登录后检查导航和设置页面；在中文页面编辑表单再切换语言，确认内容保留；打开术语、数据目录和图表，检查动态标题、日期、数字、提示及弹窗。
