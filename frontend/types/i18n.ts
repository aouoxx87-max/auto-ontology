// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export type Locale = 'en' | 'zh-CN';
export type MessageValues = Record<string, string | number>;
export type Translator = (message: string, values?: MessageValues) => string;
