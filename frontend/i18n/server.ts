// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import 'server-only';
import { cache } from 'react';
import { cookies, headers } from 'next/headers';
import { LOCALE_COOKIE, resolveLocale } from './locale';
import { createTranslator } from './translate';

export const getLocale = cache(async () => {
	const [cookieStore, requestHeaders] = await Promise.all([cookies(), headers()]);
	return resolveLocale(
		cookieStore.get(LOCALE_COOKIE)?.value,
		requestHeaders.get('accept-language'),
	);
});

export const getTranslations = async () => createTranslator(await getLocale());
