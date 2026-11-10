// 与服务端 REST / WebSocket 消息对应的数据模型（见 docs/protocols/rest-api.md）。

double? _d(Object? v) => v == null ? null : (v as num).toDouble();

DateTime? tsToDate(Object? v) {
  final d = _d(v);
  return d == null ? null : DateTime.fromMillisecondsSinceEpoch((d * 1000).round());
}

class ItemState {
  final bool read;
  final bool starred;
  final String todo; // '' / todo / doing / done
  final bool hidden;
  final double? deadlineOverride;
  final String note;
  final bool archived; // 日程：已归档

  const ItemState({
    this.read = false,
    this.starred = false,
    this.todo = '',
    this.hidden = false,
    this.deadlineOverride,
    this.note = '',
    this.archived = false,
  });

  factory ItemState.fromJson(Map<String, dynamic>? j) {
    if (j == null) return const ItemState();
    return ItemState(
      read: j['read'] == true,
      starred: j['starred'] == true,
      todo: (j['todo'] ?? '') as String,
      hidden: j['hidden'] == true,
      deadlineOverride: _d(j['deadline_override']),
      note: (j['note'] ?? '') as String,
      archived: j['archived'] == true,
    );
  }

  Map<String, dynamic> toJson() => {
        'read': read,
        'starred': starred,
        'todo': todo,
        'hidden': hidden,
        'deadline_override': deadlineOverride,
        'note': note,
        'archived': archived,
      };

  ItemState copyWith({bool? read, bool? starred, String? todo, bool? hidden, String? note, bool? archived}) => ItemState(
        read: read ?? this.read,
        starred: starred ?? this.starred,
        todo: todo ?? this.todo,
        hidden: hidden ?? this.hidden,
        deadlineOverride: deadlineOverride,
        note: note ?? this.note,
        archived: archived ?? this.archived,
      );
}

class SourceRef {
  final int id;
  final String name;
  final String type;
  final double? lastSuccessAt;
  final String status;

  const SourceRef({required this.id, required this.name, required this.type, this.lastSuccessAt, this.status = 'ok'});

  factory SourceRef.fromJson(Map<String, dynamic> j) => SourceRef(
        id: j['id'] as int,
        name: (j['name'] ?? '') as String,
        type: (j['type'] ?? '') as String,
        lastSuccessAt: _d(j['last_success_at']),
        status: (j['status'] ?? 'ok') as String,
      );

  Map<String, dynamic> toJson() => {'id': id, 'name': name, 'type': type, 'last_success_at': lastSuccessAt, 'status': status};
}

class Attachment {
  final String name;
  final String url;
  final int? size;
  const Attachment(this.name, this.url, this.size);
  factory Attachment.fromJson(Map<String, dynamic> j) =>
      Attachment((j['name'] ?? '附件') as String, (j['url'] ?? '') as String, (j['size'] as num?)?.toInt());
}

class Item {
  final int id;
  final String kind; // assignment / notice / mail / rss
  final String course;
  final String title;
  final String rawTitle;
  final String summary;
  final String url;
  final double? deadlineAt;
  final double? publishedAt;
  final int version;
  final bool deleted;
  final int sourceId;
  final double? firstSeenAt;
  final double? updatedAt;
  final List<Attachment> attachments;
  final String requirements;
  final List<String> channels;
  final Map<String, dynamic> facts;
  final String category;
  final String changeNote;
  final bool importantChange;
  final SourceRef? source;
  final ItemState state;
  final int score;
  final String priority; // urgent / normal / low
  final List<String> reasons;
  final String body;
  final Map<String, dynamic> raw;

  const Item({
    required this.id,
    required this.kind,
    required this.course,
    required this.title,
    required this.rawTitle,
    required this.summary,
    required this.url,
    required this.deadlineAt,
    required this.publishedAt,
    required this.version,
    required this.deleted,
    required this.sourceId,
    required this.firstSeenAt,
    required this.updatedAt,
    required this.attachments,
    required this.requirements,
    required this.channels,
    required this.facts,
    required this.category,
    required this.changeNote,
    required this.importantChange,
    required this.source,
    required this.state,
    required this.score,
    required this.priority,
    required this.reasons,
    required this.body,
    required this.raw,
  });

  factory Item.fromJson(Map<String, dynamic> j) => Item(
        id: j['id'] as int,
        kind: (j['kind'] ?? 'notice') as String,
        course: (j['course'] ?? '') as String,
        title: (j['title'] ?? '') as String,
        rawTitle: (j['raw_title'] ?? j['title'] ?? '') as String,
        summary: (j['summary'] ?? '') as String,
        url: (j['url'] ?? '') as String,
        deadlineAt: _d(j['deadline_at']),
        publishedAt: _d(j['published_at']),
        version: (j['version'] ?? 1) as int,
        deleted: j['deleted'] == true,
        sourceId: (j['source_id'] ?? 0) as int,
        firstSeenAt: _d(j['first_seen_at']),
        updatedAt: _d(j['updated_at']),
        attachments: ((j['attachments'] ?? []) as List).map((e) => Attachment.fromJson(Map<String, dynamic>.from(e as Map))).toList(),
        requirements: (j['requirements'] ?? '') as String,
        channels: ((j['channels'] ?? []) as List).map((e) => e.toString()).toList(),
        facts: Map<String, dynamic>.from((j['facts'] ?? {}) as Map),
        category: (j['category'] ?? '') as String,
        changeNote: (j['change_note'] ?? '') as String,
        importantChange: j['important_change'] == true,
        source: j['source'] == null ? null : SourceRef.fromJson(Map<String, dynamic>.from(j['source'] as Map)),
        state: ItemState.fromJson(j['state'] == null ? null : Map<String, dynamic>.from(j['state'] as Map)),
        score: (j['score'] ?? 0) as int,
        priority: (j['priority'] ?? 'low') as String,
        reasons: ((j['reasons'] ?? []) as List).map((e) => e.toString()).toList(),
        body: (j['body'] ?? '') as String,
        raw: j,
      );

  /// 截止时间：服务端返回的已是生效值（用户修改优先，IC-002）；旧数据再看 deadline_override。
  double? get effectiveDeadline {
    final f = fields['deadline_at'];
    if (f != null && f.edited) return f.value == null ? null : (f.value as num).toDouble();
    return state.deadlineOverride ?? deadlineAt;
  }

  // ---- 新基线（IC-002）：三类事项、状态、用户修改、监测 ----

  /// 待办 todo／日程 event／通知 notice。旧服务端没有这个字段时按渠道类型推断。
  String get type => (raw['type'] as String?) ?? (kind == 'assignment' ? 'todo' : 'notice');

  /// 按类型的处理状态：open/done、active/archived、unread/read。
  String get status => switch (type) {
        'todo' => isDone ? 'done' : 'open',
        'event' => state.archived ? 'archived' : 'active',
        _ => state.read ? 'read' : 'unread',
      };
  double? get startAt => _d(raw['start_at']);
  double? get endAt => _d(raw['end_at']);
  String get location => (raw['location'] ?? '') as String;
  String get origin => (raw['origin'] ?? 'source') as String;
  String get pageUrl {
    final p = raw['page_url'];
    return p is String && p.isNotEmpty ? p : url;
  }

  String get locator => (raw['locator'] ?? '') as String;
  Map<String, FieldInfo> get fields {
    final f = raw['fields'];
    if (f is! Map) return const {};
    return {for (final e in f.entries) e.key as String: FieldInfo.fromJson(Map<String, dynamic>.from(e.value as Map))};
  }

  List<String> get conflicts => ((raw['conflicts'] ?? []) as List).map((e) => e.toString()).toList();
  MonitorInfo get monitor =>
      MonitorInfo.fromJson(raw['monitor'] is Map ? Map<String, dynamic>.from(raw['monitor'] as Map) : null);
  DateTime? get deadline => tsToDate(effectiveDeadline);
  DateTime get sortTime => tsToDate(publishedAt ?? firstSeenAt) ?? DateTime.fromMillisecondsSinceEpoch(0);
  bool get isAssignment => kind == 'assignment';
  bool get isDone => state.todo == 'done';
  bool get isEvent => type == 'event';

  Item withState(ItemState s) => Item.fromJson({...raw, 'state': s.toJson()});

  /// 合并服务端推送：保留本地个人状态（若推送不带 state）。
  Item merge(Map<String, dynamic> j) {
    final next = {...raw, ...j};
    if (j['state'] == null) next['state'] = state.toJson();
    if (j['body'] == null || (j['body'] as String).isEmpty) next['body'] = body;
    return Item.fromJson(next);
  }

  Map<String, dynamic> toJson() => {...raw, 'state': state.toJson()};
}

/// 一个可修改字段：生效值、来源当前值、是否改过、是否冲突（IC-002 4.1）。
class FieldInfo {
  final Object? value;
  final Object? source;
  final bool edited;
  final bool conflict;
  const FieldInfo({this.value, this.source, this.edited = false, this.conflict = false});
  factory FieldInfo.fromJson(Map<String, dynamic> j) =>
      FieldInfo(value: j['value'], source: j['source'], edited: j['edited'] == true, conflict: j['conflict'] == true);
}

/// 事项的监测状态（IC-002 4.2）。
class MonitorInfo {
  final String status; // unsupported / disabled / pending / unchanged / changed / failed
  final bool supported;
  final bool enabled;
  final double? lastCheckedAt;
  final double? lastSuccessAt;
  final String errorCode;
  final String errorMessage;
  final double? nextCheckAt;
  const MonitorInfo({
    this.status = 'unsupported',
    this.supported = false,
    this.enabled = false,
    this.lastCheckedAt,
    this.lastSuccessAt,
    this.errorCode = '',
    this.errorMessage = '',
    this.nextCheckAt,
  });
  factory MonitorInfo.fromJson(Map<String, dynamic>? j) {
    if (j == null) return const MonitorInfo();
    final err = j['error'] is Map ? Map<String, dynamic>.from(j['error'] as Map) : const <String, dynamic>{};
    return MonitorInfo(
      status: (j['status'] ?? 'unsupported') as String,
      supported: j['supported'] == true,
      enabled: j['enabled'] == true,
      lastCheckedAt: _d(j['last_checked_at']),
      lastSuccessAt: _d(j['last_success_at']),
      errorCode: (err['code'] ?? '').toString(),
      errorMessage: (err['message'] ?? '').toString(),
      nextCheckAt: _d(j['next_check_at']),
    );
  }
}

class Me {
  final int id;
  final String email;
  final String name;
  final String grade;
  final String major;
  final List<String> courses;
  final String digestTime;
  final String quietStart;
  final String quietEnd;
  final bool digestEmail;
  final String mqttUser;
  final String mqttPassword;

  Me({
    required this.id,
    required this.email,
    required this.name,
    required this.grade,
    required this.major,
    required this.courses,
    required this.digestTime,
    required this.quietStart,
    required this.quietEnd,
    this.digestEmail = false,
    required this.mqttUser,
    required this.mqttPassword,
  });

  factory Me.fromJson(Map<String, dynamic> j) {
    final mq = Map<String, dynamic>.from((j['mqtt'] ?? {}) as Map);
    return Me(
      id: j['id'] as int,
      email: (j['email'] ?? '') as String,
      name: (j['name'] ?? '') as String,
      grade: (j['grade'] ?? '') as String,
      major: (j['major'] ?? '') as String,
      courses: ((j['courses'] ?? []) as List).map((e) => e.toString()).toList(),
      digestTime: (j['digest_time'] ?? '08:00') as String,
      quietStart: (j['quiet_start'] ?? '23:00') as String,
      quietEnd: (j['quiet_end'] ?? '07:00') as String,
      digestEmail: j['digest_email'] == true,
      mqttUser: (mq['username'] ?? '') as String,
      mqttPassword: (mq['password'] ?? '') as String,
    );
  }
}

class Source {
  final int id;
  final String name;
  final String type;
  final String endpoint;
  final String template;
  final String status; // pending / ok / failed / need_login
  final double? lastCheckedAt;
  final double? lastSuccessAt;
  final double? lastChangeAt;
  final String? lastError;
  final int failCount;
  final double weight;
  final bool muted;
  final bool hasLogin;
  final bool shared;
  final bool viaAgent;
  final int itemCount;
  final double? savedRatio;
  final double intervalS;

  Source({
    required this.id,
    required this.name,
    required this.type,
    required this.endpoint,
    required this.template,
    required this.status,
    required this.lastCheckedAt,
    required this.lastSuccessAt,
    required this.lastChangeAt,
    required this.lastError,
    required this.failCount,
    required this.weight,
    required this.muted,
    required this.hasLogin,
    required this.shared,
    required this.viaAgent,
    required this.itemCount,
    required this.savedRatio,
    required this.intervalS,
  });

  factory Source.fromJson(Map<String, dynamic> j) => Source(
        id: j['id'] as int,
        name: (j['name'] ?? '') as String,
        type: (j['type'] ?? '') as String,
        endpoint: (j['endpoint'] ?? '') as String,
        template: (j['template'] ?? '') as String,
        status: (j['status'] ?? 'pending') as String,
        lastCheckedAt: _d(j['last_checked_at']),
        lastSuccessAt: _d(j['last_success_at']),
        lastChangeAt: _d(j['last_change_at']),
        lastError: j['last_error'] as String?,
        failCount: (j['fail_count'] ?? 0) as int,
        weight: _d(j['weight']) ?? 0.6,
        muted: j['muted'] == true,
        hasLogin: j['has_login'] == true,
        shared: j['shared'] == true,
        viaAgent: (j['via_agent'] ?? 0) == 1 || j['via_agent'] == true,
        itemCount: (j['item_count'] ?? 0) as int,
        savedRatio: _d(j['saved_ratio']),
        intervalS: _d(j['interval_s']) ?? 600,
      );

  bool get needsLogin => status == 'need_login';
  bool get isMail => type == 'imap' || type == 'pop3';
}

class SourceTemplate {
  final String id;
  final String name;
  final String type;
  final String endpoint;
  final String description;
  final bool needsLogin;
  final bool shared;
  final String icon;

  SourceTemplate.fromJson(Map<String, dynamic> j)
      : id = j['id'] as String,
        name = j['name'] as String,
        type = j['type'] as String,
        endpoint = (j['endpoint'] ?? '') as String,
        description = (j['description'] ?? '') as String,
        needsLogin = j['needs_login'] == true,
        shared = j['shared'] == true,
        icon = (j['icon'] ?? 'link') as String;
}

class ItemVersion {
  final int version;
  final Map<String, dynamic> changed;
  final bool important;
  final String note;
  final double detectedAt;
  final Map<String, dynamic> snapshot; // 该版本的来源内容（IC-002 4.3），用于显示差异

  ItemVersion.fromJson(Map<String, dynamic> j)
      : version = j['version'] as int,
        changed = Map<String, dynamic>.from((j['changed_fields'] ?? {}) as Map),
        important = j['important'] == true,
        note = (j['change_note'] ?? '') as String,
        detectedAt = (j['detected_at'] as num).toDouble(),
        snapshot = Map<String, dynamic>.from((j['snapshot'] ?? {}) as Map);
}

class Teacher {
  final String name;
  final String title;
  final String office;
  final String phone;
  final String email;
  final String url;
  Teacher.fromJson(Map<String, dynamic> j)
      : name = (j['name'] ?? '') as String,
        title = (j['title'] ?? '') as String,
        office = (j['office'] ?? '') as String,
        phone = (j['phone'] ?? '') as String,
        email = (j['email'] ?? '') as String,
        url = (j['url'] ?? '') as String;
}

class Course {
  final String name;
  final List<Item> assignments;
  final List<Item> notices;
  final List<Teacher> teachers;
  final int open;
  Course.fromJson(Map<String, dynamic> j)
      : name = j['name'] as String,
        assignments = ((j['assignments'] ?? []) as List).map((e) => Item.fromJson(Map<String, dynamic>.from(e as Map))).toList(),
        notices = ((j['notices'] ?? []) as List).map((e) => Item.fromJson(Map<String, dynamic>.from(e as Map))).toList(),
        teachers = ((j['teachers'] ?? []) as List).map((e) => Teacher.fromJson(Map<String, dynamic>.from(e as Map))).toList(),
        open = (j['open'] ?? 0) as int;
}

class Rule {
  final String kind; // keyword / sender / source
  final String pattern;
  final double boost;
  const Rule(this.kind, this.pattern, this.boost);
  factory Rule.fromJson(Map<String, dynamic> j) => Rule(j['kind'] as String, j['pattern'] as String, (j['boost'] as num).toDouble());
  Map<String, dynamic> toJson() => {'kind': kind, 'pattern': pattern, 'boost': boost};
}

class DashWidget {
  final String id;
  final String type;
  final String title;
  final int span;
  const DashWidget(this.id, this.type, this.title, this.span);
  factory DashWidget.fromJson(Map<String, dynamic> j) =>
      DashWidget(j['id'] as String, j['type'] as String, (j['title'] ?? '') as String, (j['span'] ?? 1) as int);
  Map<String, dynamic> toJson() => {'id': id, 'type': type, 'title': title, 'span': span};
}
