// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Locale } from '../types/i18n';

export const DEFAULT_LOCALE: Locale = 'en';
export const LOCALE_COOKIE = 'auto-ontology-locale';
export const LOCALE_NAMES: Record<Locale, string> = { en: 'English', 'zh-CN': '简体中文' };

export const isLocale = (value: unknown): value is Locale => value === 'en' || value === 'zh-CN';

export const resolveLocale = (
	cookie: string | undefined,
	acceptLanguage: string | null,
): Locale => {
	if (isLocale(cookie)) return cookie;
	const languages = (acceptLanguage ?? '')
		.split(',')
		.map((entry) => {
			const [tag, ...parameters] = entry.trim().toLowerCase().split(';');
			const quality = parameters.find((parameter) => parameter.trim().startsWith('q='));
			return { tag, weight: quality == null ? 1 : Number(quality.trim().slice(2)) };
		})
		.filter(({ weight }) => Number.isFinite(weight) && weight > 0 && weight <= 1)
		.sort((a, b) => b.weight - a.weight);
	for (const { tag } of languages) {
		if (/^en(?:-|$)/.test(tag)) return 'en';
		if (tag === 'zh' || /^zh-(?:cn|sg|hans)(?:-|$)/.test(tag)) return 'zh-CN';
	}
	return DEFAULT_LOCALE;
};
