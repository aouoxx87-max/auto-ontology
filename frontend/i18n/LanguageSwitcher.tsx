// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { useLocale, useTranslations } from './LocaleProvider';
import { isLocale, LOCALE_COOKIE, LOCALE_NAMES } from './locale';

export const LanguageSwitcher = () => {
	const locale = useLocale();
	const t = useTranslations();
	const router = useRouter();
	const [pending, startTransition] = useTransition();

	const changeLanguage = (value: string) => {
		if (!isLocale(value)) return;
		document.cookie = `${LOCALE_COOKIE}=${value}; Path=/; Max-Age=31536000; SameSite=Lax${window.location.protocol === 'https:' ? '; Secure' : ''}`;
		startTransition(() => router.refresh());
	};

	return (
		<label className="flex shrink-0 items-center gap-2 text-xs text-body dark:text-zinc-300">
			<span className="sr-only">{t('Language')}</span>
			<select
				value={locale}
				onChange={(event) => changeLanguage(event.target.value)}
				disabled={pending}
				aria-busy={pending}
				className="max-w-32 rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900"
			>
				{Object.entries(LOCALE_NAMES).map(([value, label]) => (
					<option key={value} value={value} lang={value}>
						{label}
					</option>
				))}
			</select>
		</label>
	);
};
