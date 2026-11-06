// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import ts from 'typescript';
import { expect, it } from 'vitest';
import messages from './messages/zh-CN.json';
import { CONNECTION_FIELDS, connectionFieldsFor, ConnectionType } from '@/enums/connection';
import { SEARCH_TYPE_LABEL, SEARCH_TYPE_TAB_LABEL } from '@/common/globalSearchMeta';
import { compactNumber, formatTick, formatValueFull } from '@/components/ResultChart/scale';
import { vi } from 'vitest';

vi.mock('@/common/icons', () => ({ IconName: {} }));

it('has Chinese messages for every literal translation call', () => {
	const missing: string[] = [];
	for (const directory of ['app', 'common', 'components', 'contexts', 'lib']) {
		for (const path of readdirSync(directory, { recursive: true }) as string[]) {
			if (!/\.tsx?$/.test(path) || path.startsWith('api/')) continue;
			const file = join(directory, path);
			const source = ts.createSourceFile(
				file,
				readFileSync(file, 'utf8'),
				ts.ScriptTarget.Latest,
				true,
			);
			const visit = (node: ts.Node) => {
				if (ts.isCallExpression(node) && node.expression.getText(source) === 't') {
					const key = node.arguments[0];
					if (
						key &&
						ts.isStringLiteral(key) &&
						key.text !== '#' &&
						!Object.hasOwn(messages, key.text)
					)
						missing.push(`${file}: ${key.text}`);
				}
				ts.forEachChild(node, visit);
			};
			visit(source);
		}
	}
	expect(missing).toEqual([]);
});

it('covers the fixed search type and connector field labels', () => {
	const labels = [...Object.values(SEARCH_TYPE_LABEL), ...Object.values(SEARCH_TYPE_TAB_LABEL)];
	for (const kind of Object.keys(CONNECTION_FIELDS) as ConnectionType[]) {
		for (const field of connectionFieldsFor(kind)) {
			labels.push(field.label);
			if (field.hint) labels.push(field.hint);
		}
	}
	expect(labels.filter((label) => !Object.hasOwn(messages, label))).toEqual([]);
});

it('uses Chinese compact units without changing currency semantics', () => {
	expect(compactNumber(12000, 'zh-CN')).toBe('1.2万');
	expect(compactNumber(12000, 'en')).toBe('12K');
	expect(formatTick(200000000, 'number', 'zh-CN')).toBe('2亿');
	expect(formatValueFull(1234.5, 'currency', 'zh-CN')).toBe('US$1,234.50');
	expect(formatValueFull(0.125, 'percent', 'zh-CN')).toBe('12.5%');
	expect(compactNumber(Number.NaN, 'zh-CN')).toBe('–');
});
