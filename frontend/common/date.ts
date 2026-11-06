// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import type { Locale } from '@/types/i18n';

export type DateInput = string | number | Date;

export const formatDate = (value: DateInput, format?: string, locale: Locale = 'en'): string =>
	dayjs(value)
		.locale(locale === 'zh-CN' ? 'zh-cn' : 'en')
		.format(format ?? (locale === 'zh-CN' ? 'YYYY年M月D日' : 'MMM DD YYYY'));
