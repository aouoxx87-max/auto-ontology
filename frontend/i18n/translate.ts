// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import zhCN from './messages/zh-CN.json';
import type { Locale, MessageValues, Translator } from '../types/i18n';

const dictionaries: Record<Locale, Readonly<Record<string, string>>> = { en: {}, 'zh-CN': zhCN };

export const createTranslator =
	(locale: Locale): Translator =>
	(message: string, values?: MessageValues): string => {
		const dictionary = dictionaries[locale];
		const translated = Object.hasOwn(dictionary, message) ? dictionary[message] : message;
		return translated.replace(/\{(\w+)\}/g, (placeholder, name: string) =>
			values != null && Object.hasOwn(values, name) ? String(values[name]) : placeholder,
		);
	};
