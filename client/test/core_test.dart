import 'package:flutter_test/flutter_test.dart';
import 'package:gleaner/core/format.dart';
import 'package:gleaner/core/models.dart';

void main() {
  group('relative time', () {
    final now = DateTime(2026, 10, 22, 12, 0);
    test('just now and minutes', () {
      expect(relative(now.subtract(const Duration(seconds: 50)), now: now), '刚刚');
      expect(relative(now.subtract(const Duration(minutes: 10)), now: now), '10 分钟前');
      expect(relative(now.subtract(const Duration(hours: 3)), now: now), '3 小时前');
      expect(relative(DateTime(2026, 10, 21, 14, 0), now: now), '昨天 14:00');
      expect(relative(null, now: now), '从未');
    });
  });

  group('countdown', () {
    final now = DateTime(2026, 10, 22, 12, 0);
    test('future and past', () {
      expect(countdown(now.add(const Duration(minutes: 30)), now: now), '还剩 30 分钟');
      expect(countdown(now.add(const Duration(hours: 5)), now: now), '还剩 5 小时');
      expect(countdown(now.add(const Duration(days: 1, hours: 18)), now: now), '还剩 1 天 18 小时');
      expect(countdown(now.add(const Duration(days: 9)), now: now), '还剩 9 天');
      expect(countdown(now.subtract(const Duration(days: 2)), now: now), '已截止 2 天');
    });
  });

  test('shortCourse strips course code', () {
    expect(shortCourse('CS3105 网络编程'), '网络编程');
    expect(shortCourse('网络编程'), '网络编程');
  });

  group('Item model', () {
    final json = {
      'id': 7,
      'kind': 'assignment',
      'course': 'CS3105 网络编程',
      'title': '实验一',
      'deadline_at': 1792771140.0,
      'version': 2,
      'source_id': 1,
      'attachments': [
        {'name': 'a.pdf', 'url': 'http://x/a.pdf', 'size': 12}
      ],
      'channels': ['moodle', 'imap'],
      'state': {'read': false, 'starred': true, 'todo': 'todo'},
      'priority': 'urgent',
      'score': 88,
      'important_change': true,
      'change_note': '截止提前 2 天',
    };

    test('parses server json', () {
      final it = Item.fromJson(json);
      expect(it.isAssignment, isTrue);
      expect(it.state.starred, isTrue);
      expect(it.channels, ['moodle', 'imap']);
      expect(it.attachments.single.name, 'a.pdf');
      expect(it.deadline, isNotNull);
    });

    test('merge keeps local state when push has none', () {
      final it = Item.fromJson(json);
      final merged = it.merge({'id': 7, 'title': '实验一（修订）', 'version': 3});
      expect(merged.title, '实验一（修订）');
      expect(merged.version, 3);
      expect(merged.state.starred, isTrue);
      expect(merged.state.todo, 'todo');
    });

    test('user override wins for deadline', () {
      final it = Item.fromJson({
        ...json,
        'state': {'deadline_override': 1800000000.0}
      });
      expect(it.effectiveDeadline, 1800000000.0);
    });
  });
}
