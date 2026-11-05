import 'dart:convert';

import 'package:flutter/material.dart';

/// Source changes remain separate from personal notes and deadline overrides.
class SourceChanges extends StatelessWidget {
  final Map<String, dynamic> changed;
  const SourceChanges(this.changed, {super.key});
  String value(Object? v) => v == null
      ? '未提供'
      : v is Map || v is List
      ? const JsonEncoder.withIndent('  ').convert(v)
      : '$v';
  @override
  Widget build(BuildContext context) => Column(
    children: [
      for (final entry in changed.entries)
        if (entry.value is List && (entry.value as List).length == 2)
          ExpansionTile(
            title: Text(
              const {
                    'body': '原文内容',
                    'title': '标题',
                    'deadline_at': '来源截止时间',
                    'requirements': '提交要求',
                    'source_fields': '来源字段',
                  }[entry.key] ??
                  entry.key,
            ),
            children: [
              Padding(
                padding: const EdgeInsets.all(8),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: SelectableText(
                    '变更前：\n${value((entry.value as List)[0])}',
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(8),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: SelectableText(
                    '变更后：\n${value((entry.value as List)[1])}',
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.primary,
                    ),
                  ),
                ),
              ),
            ],
          ),
    ],
  );
}
