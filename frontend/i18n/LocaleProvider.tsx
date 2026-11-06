// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { createTranslator } from './translate';
import type { Locale } from '@/types/i18n';

const LocaleContext = createContext<Locale>('en');

export const LocaleProvider = ({ locale, children }: { locale: Locale; children: ReactNode }) => (
	<LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>
);

export const useLocale = () => useContext(LocaleContext);
export const useTranslations = () => {
	const locale = useLocale();
	return useMemo(() => createTranslator(locale), [locale]);
};
