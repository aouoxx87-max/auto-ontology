// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
	resolve: { alias: { '@': fileURLToPath(new URL('.', import.meta.url)) } },
	test: { environment: 'node', include: ['i18n/**/*.test.{ts,tsx}'] },
});
