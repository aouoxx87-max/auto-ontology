// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { isLocale, resolveLocale } from './locale';
import { createTranslator } from './translate';
import { formatDate } from '@/common/date';
import zhCN from './messages/zh-CN.json';

describe('request locale', () => {
	it.each([
		['zh-CN', 'en-US', 'zh-CN'],
		['en', 'zh-CN', 'en'],
		[undefined, 'zh-CN,zh;q=0.9,en;q=0.8', 'zh-CN'],
		[undefined, 'en-US;q=0.8,zh-Hans;q=0.9', 'zh-CN'],
		[undefined, 'zh;q=0.2,en-GB;q=0.9', 'en'],
		[undefined, 'fr-FR,zh-SG;q=0.5', 'zh-CN'],
		['<script>', 'zh-Hans-CN', 'zh-CN'],
		[undefined, 'zh-TW,zh-Hant;q=0.9,en;q=0.5', 'en'],
		[undefined, 'zh-CN;q=0,en', 'en'],
		[undefined, 'zh-CN;q=abc,en', 'en'],
		[undefined, 'zh-CN;q=2,en', 'en'],
		[undefined, null, 'en'],
		[undefined, '*', 'en'],
	])('resolves cookie %s and language %s to %s', (cookie, language, expected) => {
		expect(resolveLocale(cookie, language)).toBe(expected);
	});
	it('accepts only supported cookie values', () => {
		expect(isLocale('zh-CN')).toBe(true);
		expect(isLocale('en')).toBe(true);
		expect(isLocale('zh')).toBe(false);
		expect(isLocale(null)).toBe(false);
	});
});

describe('message catalogs', () => {
	it('translates Chinese and preserves English and unknown messages', () => {
		expect(createTranslator('zh-CN')('Settings')).toBe('设置');
		expect(createTranslator('en')('Settings')).toBe('Settings');
		expect(createTranslator('zh-CN')('An unknown message')).toBe('An unknown message');
		expect(createTranslator('zh-CN')('constructor')).toBe('constructor');
	});
	it('interpolates named values without evaluating or recursively replacing them', () => {
		const t = createTranslator('zh-CN');
		expect(t('Actions for {name}', { name: '$& {other} <script>' })).toBe(
			'$& {other} <script> 的操作',
		);
		expect(t('Selected ({count})', { count: 0 })).toBe('已选择（0）');
		expect(t('Actions for {name}')).toBe('{name} 的操作');
	});
	it('keeps placeholders identical in every translation', () => {
		const parameters = (value: string) =>
			[...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
		for (const [source, translation] of Object.entries(zhCN)) {
			expect(translation.trim(), source).not.toBe('');
			expect(parameters(translation), source).toEqual(parameters(source));
		}
	});
	it('isolates concurrent request translators', async () => {
		const results = await Promise.all(
			['en', 'zh-CN', 'en'].map(async (locale) => {
				const t = createTranslator(locale as 'en' | 'zh-CN');
				await Promise.resolve();
				return t('Settings');
			}),
		);
		expect(results).toEqual(['Settings', '设置', 'Settings']);
	});
});

describe('localized dates', () => {
	const date = new Date(2026, 10, 6, 13, 14);
	it('formats default dates for the selected locale without mutating dayjs globally', () => {
		expect(formatDate(date, undefined, 'zh-CN')).toBe('2026年11月6日');
		expect(formatDate(date)).toBe('Nov 06 2026');
		expect(formatDate(date, 'MMM DD YYYY HH:mm', 'zh-CN')).toBe('11月 06 2026 13:14');
	});
	it('preserves explicit machine-readable formats', () => {
		expect(formatDate(date, 'YYYY-MM', 'zh-CN')).toBe('2026-11');
	});
});
