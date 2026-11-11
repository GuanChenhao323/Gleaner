import 'package:flutter/material.dart';

import '../../core/api.dart';
import '../../widgets/common.dart';

/// Keep transport/ownership failure feedback separate from item rendering.
class ItemLoadFailure extends StatelessWidget {
  final Object? error;
  final String email;
  final VoidCallback onRetry;
  final VoidCallback onSources;

  const ItemLoadFailure({
    super.key,
    required this.error,
    required this.email,
    required this.onRetry,
    required this.onSources,
  });

  @override
  Widget build(BuildContext context) {
    final status = error is ApiException
        ? (error as ApiException).status
        : null;
    final message = switch (status) {
      404 => '事项不存在或不属于当前账号。请确认工作台与插件使用同一 Campus Radar 邮箱。',
      401 => '登录已失效，请在工作台重新登录。',
      _ => '未能读取详情，请检查后端连接后重试。',
    };
    return EmptyState(
      icon: Icons.info_outline,
      title: '无法打开这条事项',
      message: '$message\n当前工作台账号：${email.isEmpty ? '未登录' : email}',
      action: Wrap(
        spacing: 8,
        children: [
          OutlinedButton(onPressed: onRetry, child: const Text('重试')),
          TextButton(onPressed: onSources, child: const Text('返回信息源')),
        ],
      ),
    );
  }
}
