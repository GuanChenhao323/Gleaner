import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Entry availability is independent of authentication and of saved-item counts.
class CampusSourceEntry {
  final String id;
  final String name;
  final String url;
  final bool requiresLogin;
  final String scope;

  const CampusSourceEntry({
    required this.id,
    required this.name,
    required this.url,
    required this.requiresLogin,
    required this.scope,
  });
}

const campusSourceEntries = [
  CampusSourceEntry(
    id: 'student',
    name: '学院公告／学生系统',
    url: 'https://student-wmweb.must.edu.mo/',
    requiresLogin: true,
    scope: '登录后可读取首页公告与资讯；课表需打开独立课表界面。',
  ),
  CampusSourceEntry(
    id: 'fie',
    name: '教师信息',
    url: 'https://fie.must.edu.mo/person/id-828.html?locale=zh_MO',
    requiresLogin: false,
    scope: '指定的公开人员目录；进入个人详情后读取资料。',
  ),
  CampusSourceEntry(
    id: 'moodle',
    name: 'Moodle 课程与作业',
    url: 'https://moodle.must.edu.mo/my/',
    requiresLogin: true,
    scope: '登录后查看课程入口，进入具体作业读取要求。',
  ),
];

class CampusSourceEntries extends StatelessWidget {
  const CampusSourceEntries({super.key});

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text('校园来源', style: Theme.of(context).textTheme.titleLarge),
      const Text(
        '打开原网页，在 Chrome 插件中输入想抓取的内容，抓取匹配结果并预览，再一次保存。预览保留在本机插件中；'
        '保存后的事项才进入工作台。Campus Radar 账号与学校账号分别登录。',
      ),
      for (final source in campusSourceEntries)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  source.name,
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                Text(
                  source.requiresLogin
                      ? '需在原站登录 · 本页不判断学校会话是否有效'
                      : '公开网页 · 无需学生登录',
                ),
                Text(source.scope),
                TextButton.icon(
                  onPressed: () => launchUrl(Uri.parse(source.url)),
                  icon: const Icon(Icons.open_in_new),
                  label: const Text('打开来源网页'),
                ),
              ],
            ),
          ),
        ),
    ],
  );
}
