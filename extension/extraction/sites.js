/** Product entries are independent of saved items and of legacy demo subscriptions. */
export const SOURCES = Object.freeze([
  { id: 'student', name: '学院公告／学生系统', private: true, url: 'https://student-wmweb.must.edu.mo/' },
  { id: 'fie', name: '教师信息', private: false, url: 'https://fie.must.edu.mo/person/id-828.html?locale=zh_MO' },
  { id: 'moodle', name: 'Moodle 课程与作业', private: true, url: 'https://moodle.must.edu.mo/my/' },
]);

export class SiteRegistry {
  resolve(value, fixture = '') {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw Error('unsupported');
    const local = ['localhost', '127.0.0.1'].includes(url.hostname);
    const source = local && ['student', 'fie', 'moodle'].includes(fixture) ? fixture : ({
      'student-wmweb.must.edu.mo': 'student',
      'infoportal-web.must.edu.mo': 'student',
      'classtimetable-coes-wmweb.must.edu.mo': 'student',
      'fie.must.edu.mo': 'fie',
      'moodle.must.edu.mo': 'moodle',
    })[url.hostname];
    if (!source || (!local && url.protocol !== 'https:')) throw Error('unsupported');
    return { source, local, private: source !== 'fie', url: url.href };
  }
}

export function safeUrl(value, base) {
  try {
    const u = new URL(value, base);
    if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password) return '';
    // Authenticated redirects and signed resource URLs are never candidate source links.
    if ([...u.searchParams.keys()].some(k => /token|ticket|session|password|secret|authorization/i.test(k))) return '';
    return u.href;
  } catch { return ''; }
}

/** UI suggestion only; the adapter still validates source, route and scope. */
export function suggestSection(value) {
  const u = new URL(value);
  if (u.hostname === 'fie.must.edu.mo' || u.pathname.startsWith('/person/')) return 'people';
  if (u.hostname === 'classtimetable-coes-wmweb.must.edu.mo' || /timetable/.test(u.pathname + u.hash)) return 'timetable';
  if (u.hostname === 'moodle.must.edu.mo' || /^\/(my\/|course\/|mod\/assign\/)/.test(u.pathname)) return 'moodle';
  if (u.hostname === 'infoportal-web.must.edu.mo' && !/(^|\.)notice$/.test(u.searchParams.get('category') || '')) return 'news';
  return 'notices';
}
