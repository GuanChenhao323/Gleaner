import 'package:flutter/material.dart';

import '../core/format.dart';
import '../core/models.dart';
import '../l10n/app_localizations.dart';
import '../theme.dart';

class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? message;
  final Widget? action;
  const EmptyState({super.key, required this.icon, required this.title, this.message, this.action});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(
            width: 88,
            height: 88,
            decoration: BoxDecoration(color: cs.primaryContainer.withValues(alpha: 0.6), shape: BoxShape.circle),
            child: Icon(icon, size: 40, color: cs.onPrimaryContainer),
          ),
          const SizedBox(height: 20),
          Text(title, style: Theme.of(context).textTheme.titleMedium, textAlign: TextAlign.center),
          if (message != null) ...[
            const SizedBox(height: 8),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 360),
              child: Text(message!, style: TextStyle(color: cs.onSurfaceVariant), textAlign: TextAlign.center),
            ),
          ],
          if (action != null) ...[const SizedBox(height: 20), action!],
        ]),
      ),
    );
  }
}

class SectionHeader extends StatelessWidget {
  final String title;
  final String? trailing;
  final Widget? action;
  const SectionHeader(this.title, {super.key, this.trailing, this.action});

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 16, 4, 8),
      child: Row(children: [
        Text(title, style: t.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700, color: t.colorScheme.onSurface)),
        if (trailing != null) ...[
          const SizedBox(width: 8),
          Text(trailing!, style: t.textTheme.labelMedium?.copyWith(color: t.colorScheme.onSurfaceVariant)),
        ],
        const Spacer(),
        ?action,
      ]),
    );
  }
}

class Pill extends StatelessWidget {
  final String label;
  final Color color;
  final IconData? icon;
  final bool filled;
  const Pill(this.label, {super.key, required this.color, this.icon, this.filled = false});

  @override
  Widget build(BuildContext context) {
    final bg = filled ? color : color.withValues(alpha: 0.12);
    final fg = filled ? Colors.white : color;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (icon != null) ...[Icon(icon, size: 13, color: fg), const SizedBox(width: 4)],
        Text(label, style: TextStyle(color: fg, fontSize: 12, fontWeight: FontWeight.w600, height: 1.2)),
      ]),
    );
  }
}

class CourseTag extends StatelessWidget {
  final String course;
  final bool muted;
  const CourseTag(this.course, {super.key, this.muted = false});
  @override
  Widget build(BuildContext context) {
    if (course.isEmpty) return const SizedBox.shrink();
    final cs = Theme.of(context).colorScheme;
    final c = muted ? cs.outline : Brand.course(course);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Container(width: 8, height: 8, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
      const SizedBox(width: 6),
      Flexible(
        child: Text(shortCourse(course),
            overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.labelMedium?.copyWith(color: cs.onSurfaceVariant)),
      ),
    ]);
  }
}

class DeadlineBadge extends StatelessWidget {
  final DateTime due;
  final bool done;
  const DeadlineBadge(this.due, {super.key, this.done = false});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (done) return Pill(l10n.completed, color: Brand.ok, icon: Icons.check);
    final u = urgencyOf(due);
    return Pill(countdown(due, context), color: urgencyColor(context, u), icon: Icons.schedule, filled: u == Urgency.critical);
  }
}


/// 截止时间变化等重要变更的醒目标记。
class ChangeBadge extends StatelessWidget {
  final String note;
  const ChangeBadge(this.note, {super.key});
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(color: cs.tertiaryContainer, borderRadius: BorderRadius.circular(8)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.auto_awesome, size: 14, color: cs.onTertiaryContainer),
        const SizedBox(width: 4),
        Flexible(
          child: Text(localizeChangeNote(note, context),
              maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: cs.onTertiaryContainer, fontSize: 12, fontWeight: FontWeight.w700)),
        ),
      ]),
    );
  }
}

class SourceStatusPill extends StatelessWidget {
  final Source source;
  const SourceStatusPill(this.source, {super.key});
  @override
  Widget build(BuildContext context) {
    final s = sourceStatus(context, source);
    return Pill(s.label, color: s.color, icon: s.icon);
  }
}

class Avatar extends StatelessWidget {
  final String name;
  final double size;
  const Avatar(this.name, {super.key, this.size = 36});
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final ch = name.isEmpty ? AppLocalizations.of(context).brandFallback : name.characters.first;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        gradient: LinearGradient(colors: [cs.primary, Color.lerp(cs.primary, Brand.wheat, 0.55)!], begin: Alignment.topLeft, end: Alignment.bottomRight),
        shape: BoxShape.circle,
      ),
      child: Text(ch, style: TextStyle(color: cs.onPrimary, fontWeight: FontWeight.w700, fontSize: size * 0.42)),
    );
  }
}

/// 应用品牌标志。
class GleanerLogo extends StatelessWidget {
  final double size;
  const GleanerLogo({super.key, this.size = 40});
  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(size * 0.2),
        child: Image.asset('assets/logo.png', width: size, height: size, semanticLabel: AppLocalizations.of(context).appTitle),
      );
}

void toast(BuildContext context, String msg, {bool error = false}) {
  final cs = Theme.of(context).colorScheme;
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(msg), backgroundColor: error ? cs.error : null, duration: const Duration(seconds: 3)));
}
