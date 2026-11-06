// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// @vitest-environment jsdom

import { act, useState } from 'react';
import { createRoot, hydrateRoot, type Root } from 'react-dom/client';
import { renderToString } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LanguageSwitcher } from './LanguageSwitcher';
import { LocaleProvider, useTranslations } from './LocaleProvider';
import { isLocale, LOCALE_COOKIE } from './locale';
import type { Locale } from '@/types/i18n';

const navigation = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => navigation }));

const Draft = () => {
	const t = useTranslations();
	const [draft, setDraft] = useState('');
	return (
		<>
			<button onClick={() => setDraft('尚未提交的内容')}>{t('Edit')}</button>
			<input value={draft} onChange={(event) => setDraft(event.target.value)} />
		</>
	);
};

const Screen = ({ locale }: { locale: Locale }) => (
	<LocaleProvider locale={locale}>
		<LanguageSwitcher />
		<Draft />
	</LocaleProvider>
);

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
	Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
	document.cookie = `${LOCALE_COOKIE}=; Path=/; Max-Age=0`;
	container = document.createElement('div');
	document.body.append(container);
	navigation.refresh.mockReset();
});

afterEach(async () => {
	await act(() => root?.unmount());
	container.remove();
	document.cookie = `${LOCALE_COOKIE}=; Path=/; Max-Age=0`;
	vi.restoreAllMocks();
});

describe('language switching', () => {
	it('persists a valid language and refreshes server content while retaining the draft', async () => {
		root = createRoot(container);
		navigation.refresh.mockImplementation(() => {
			const value = document.cookie
				.split('; ')
				.find((entry) => entry.startsWith(`${LOCALE_COOKIE}=`))
				?.split('=')[1];
			if (isLocale(value)) root.render(<Screen locale={value} />);
		});
		await act(() => root.render(<Screen locale="en" />));
		await act(() => container.querySelector('button')!.click());
		const select = container.querySelector('select')!;
		await act(() => {
			select.value = 'zh-CN';
			select.dispatchEvent(new Event('change', { bubbles: true }));
		});
		expect(document.cookie).toContain(`${LOCALE_COOKIE}=zh-CN`);
		expect(navigation.refresh).toHaveBeenCalledTimes(1);
		expect(container.querySelector('button')!.textContent).toBe('编辑');
		expect(container.querySelector('input')!.value).toBe('尚未提交的内容');
		expect(container.querySelector('select')!.value).toBe('zh-CN');
		await act(() => {
			select.value = 'en';
			select.dispatchEvent(new Event('change', { bubbles: true }));
		});
		expect(document.cookie).toContain(`${LOCALE_COOKIE}=en`);
		expect(container.querySelector('button')!.textContent).toBe('Edit');
		expect(container.querySelector('input')!.value).toBe('尚未提交的内容');
	});
	it('ignores unsupported select values before writing cookies', async () => {
		root = createRoot(container);
		await act(() => root.render(<Screen locale="en" />));
		const select = container.querySelector('select')!;
		await act(() => {
			select.value = 'unsupported';
			select.dispatchEvent(new Event('change', { bubbles: true }));
		});
		expect(document.cookie).not.toContain(LOCALE_COOKIE);
		expect(navigation.refresh).not.toHaveBeenCalled();
	});
	it('hydrates the Chinese server output without mismatches', async () => {
		container.innerHTML = renderToString(<Screen locale="zh-CN" />);
		const errors = vi.spyOn(console, 'error');
		await act(() => {
			root = hydrateRoot(container, <Screen locale="zh-CN" />);
		});
		expect(container.querySelector('select')!.value).toBe('zh-CN');
		expect(container.textContent).toContain('编辑');
		expect(errors).not.toHaveBeenCalled();
	});
});
