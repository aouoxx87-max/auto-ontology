// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { getTranslations } from '@/i18n/server';
import type { Metadata } from 'next';

export const generateMetadata = async (): Promise<Metadata> => {
	const t = await getTranslations();
	return { title: t('Analytics') };
};

export default function AnalyticsLayout({ children }: { children: React.ReactNode }) {
	return children;
}
