/** Deterministic input grammar. This does not infer business dates or call an LLM. */
export function normalize(value) {
  const traditional = '網絡編課業資訊獎學電郵辦師個這門當頁標題關鍵詞獲發佈電話職稱部張陳劉楊軟體計劃與時週後間';
  const simplified = '网络编课业资讯奖学电邮办师个这门当页标题关键词获发布电话职称部张陈刘杨软体计划与时周后间';
  const map = new Map([...traditional].map((c, i) => [c, [...simplified][i]]));
  return String(value || '').normalize('NFKC').toLowerCase().replace(/[\s\u200b]+/g, ' ').trim().split('').map(c => map.get(c) || c).join('');
}

export class IntentParser {
  parse(value) {
    if (typeof value !== 'string' || !value.trim()) throw Error('query_required');
    if (value.trim().length > 200) throw Error('query_too_long');
    const query = value.trim(), input = normalize(query);
    if (/今天|明天|本周|最近|之前|之后|截止|除了|排除|不包含|总结|翻译|推荐|大于|少于/.test(input)) throw Error('unsupported_query');
    const course = input.match(/(?:^|[;；])\s*课程\s*[:：]\s*([^;；]+)/)?.[1]?.trim();
    const keyword = input.match(/(?:^|[;；])\s*(?:关键词|标题)\s*[:：]\s*([^;；]+)/)?.[1]?.trim();
    const type = input.match(/(?:^|[;；])\s*类型\s*[:：]\s*([^;；]+)/)?.[1]?.trim();
    if (/[:：]/.test(input) && !course && !keyword && !type) throw Error('unsupported_query');
    if (/[:：]/.test(input) && input.split(/[;；]/).some(s => !/^\s*(课程|关键词|标题|类型)\s*[:：]\s*\S/.test(s))) throw Error('unsupported_query');
    const fields = Object.entries({ email: /邮箱|电邮|email/, office: /办公室|office/, phone: /电话|phone/, role: /职称|职务/, department: /部门/ }).filter(([, re]) => re.test(input)).map(([key]) => key).sort();
    const kind = fields.length || /老师|教师|人员|资料|履历/.test(input) ? 'people'
      : /作业|assignment/.test(type || input) ? 'assignments'
      : /课表|timetable/.test(type || input) ? 'timetable'
      : /公告|通知/.test(type || input) ? 'notices'
      : /资讯|新闻/.test(type || input) ? 'news' : 'auto';
    if (type && kind === 'auto') throw Error('unsupported_query');
    const current = /这位|这门课|当前课程|当前人员/.test(input);
    const all = /全部|所有/.test(input);
    let target = course || (keyword || type ? '' : input
      .replace(/^(?:请|帮我|抓取|采集|提取|获取|查看|关于|我要|我想要|我想|想要|想|要|只要|只抓取|只采集)+/g, '')
      .replace(/这位老师|这位教师|这位人员|这门课|当前课程|当前人员|当前页面|当前页|本页|全部|所有/g, '')
      .replace(/邮箱|电邮|email|办公室|office|电话|phone|职称|职务|部门|作业|assignment|课表|timetable|公告|通知|资讯|新闻|老师|教师|人员|资料|履历/g, '')
      .replace(/(?:相关|课程|的|和|与|及|、|\s)+$/g, '').replace(/^[的\s]+/g, '').trim());
    if (!target && kind === 'auto' && !keyword && !all) throw Error('unsupported_query');
    return { version: 2, query, kind, target, keyword: keyword || '', fields, current, all };
  }
}
