// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from './LocaleProvider';
import { LanguageSwitcher } from './LanguageSwitcher';
import { NavRail } from '@/common/NavRail';
import { SearchInput } from '@/common/SearchInput';
import { SettingsNav } from '@/components/settings/SettingsNav';
import { Label } from '@/common/Label';

vi.mock('next/navigation', () => ({
	usePathname: () => '/settings',
	useRouter: () => ({ refresh: vi.fn() }),
}));
vi.mock('@/common/icons', () => ({ Icon: () => null, IconName: {} }));

const render = (locale: 'en' | 'zh-CN') =>
	renderToStaticMarkup(
		<LocaleProvider locale={locale}>
			<LanguageSwitcher />
			<NavRail isAdmin />
			<SettingsNav connectionsEnvManaged={false} />
			<SearchInput value="Settings" onChange={() => {}} />
			<Label label="Settings" />
		</LocaleProvider>,
	);

describe('server-rendered locale', () => {
	it('renders Chinese navigation, accessible labels and selected language on the first paint', () => {
		const html = render('zh-CN');
		expect(html).toContain('title="聊天"');
		expect(html).toContain('title="使用统计"');
		expect(html).toContain('语义编译');
		expect(html).toContain('placeholder="搜索"');
		expect(html).toContain('aria-label="清除搜索"');
		expect(html).toContain('value="zh-CN" lang="zh-CN" selected=""');
		expect(html).toContain('href="/settings/connections"');
	});
	it('keeps user content untouched even if it matches a translation key', () => {
		const html = render('zh-CN');
		expect(html).toContain('value="Settings"');
		expect(html).toContain('>Settings<');
	});
	it('renders English without leaking the previous request language', () => {
		render('zh-CN');
		const html = render('en');
		expect(html).toContain('title="Chat"');
		expect(html).toContain('Semantic Compilation');
		expect(html).toContain('placeholder="Search"');
		expect(html).not.toContain('语义编译');
	});
	it('preserves role-based navigation when localized', () => {
		const html = renderToStaticMarkup(
			<LocaleProvider locale="zh-CN">
				<NavRail />
			</LocaleProvider>,
		);
		expect(html).toContain('title="聊天"');
		expect(html).not.toContain('href="/settings"');
		expect(html).not.toContain('href="/analytics"');
	});
});
