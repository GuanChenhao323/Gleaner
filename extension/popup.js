const $ = id => document.getElementById(id);
const tips = { view_mismatch: '学期、周次或视图已改变，请回原页重新识别。', route_mismatch: '页面路由已改变，未更新原事项。', preview_required: '请先读取并预览所选详情。', need_login: '请先在学校原站自行登录，再识别本页。', account_unknown: '当前页面无法可靠识别学校账号，需补充适配后才能安全保存。',
  unsupported: '此来源尚未适配。', unsupported_dom: '尚未验证此页面结构，未采集内容。', frame_unsupported: '此页面的内容在 frame 中，首版请打开独立内容页。',
  selection_missing: '选区已失效或无法定位，请回原页重新选择。', render_timeout: '页面内容加载超时，未保存。', backend_unavailable: '本地后端不可用。', backend_timeout: '后端请求超时，可查询结果后重试。',
  account_mismatch: '学校账号已切换，旧绑定已停止，请确认当前账号后重新识别。', backend_login_required: '请登录本地后端。', invalid_response: '后端响应格式异常，未确认成功。', permission_denied: '缺少该来源的访问权限。', outbox_full: '本地队列已满，请先处理失败任务。', manual_private_unsupported: '认证来源手动选区需额外账号适配，当前未支持。' };
let cfg = {}, tab = null, page = null;
const checked = new Set();
const message = async value => { const r = await chrome.runtime.sendMessage(value); if (!r?.ok) throw Error(r?.error || 'worker_unavailable'); return r.value; };
const status = text => { $('status').textContent = text; };
const run = action => async () => { try { await action(); } catch (e) { status(tips[e.message] || e.message); } };
function selected() { return [...document.querySelectorAll('[data-candidate]:checked')].map(n => page.candidates[Number(n.dataset.candidate)]); }
function render() {
  $('candidates').replaceChildren(); $('navigation').replaceChildren();
  for (const link of page.navigation || []) {
    const button = document.createElement('button'); button.textContent = `打开课程：${link.title}`;
    button.onclick = () => chrome.tabs.create({ url: link.url }); $('navigation').append(button);
  }
  page.candidates.forEach((candidate, i) => {
    const card = document.createElement('article'), label = document.createElement('label'), check = document.createElement('input');
    check.type = 'checkbox'; check.dataset.candidate = i; check.checked = checked.has(candidate.entity_id);
    label.append(check, document.createTextNode(candidate.raw.title)); card.append(label);
    const preview = document.createElement('pre'); preview.textContent = candidate.raw.text;
    const source = document.createElement('p'); source.className = 'url'; source.textContent = candidate.locator.url;
    const note = document.createElement('p'); note.textContent = candidate.needs_detail ? '尚未读取详情。勾选后点击“读取所选详情预览”。' : candidate.supported ? '可尝试后台重读；检查成功后显示实际状态。' : '仅保存，不支持监测。';
    const fields = document.createElement('pre');
    const names = {course:'课程',semester:'学期',week:'教学周',weekday:'星期',period:'节次',datetime_text:'日期／时间原文',requirements:'提交要求',department:'部门',office:'办公室',email:'邮箱',phone:'电话',role:'职务',subtype:'资料类别'};
    fields.textContent = Object.entries(candidate.raw.fields || {}).filter(([,v]) => v).map(([k,v]) => `${names[k] || k}：${v}`).join('\n');
    card.append(source, preview, fields, note); $('candidates').append(card);
    check.onchange = run(async () => { if (check.checked) checked.add(candidate.entity_id); else checked.delete(candidate.entity_id); buttons(); if (!candidate.needs_detail) await message({ type: 'highlight', tabId: tab.id, recipe: candidate.recipe }); });
  });
  buttons();
}
function buttons() {
  const choices = selected();
  $('save').disabled = !choices.length || choices.some(c => c.needs_detail);
  $('preview').disabled = !choices.some(c => c.needs_detail);
}
$('preview').onclick = run(async () => {
  for (const candidate of selected().filter(c => c.needs_detail)) {
    status(`正在读取所选详情：${candidate.raw.title}`);
    const found = await message({ type: 'preview', recipe: candidate.recipe, binding: page.binding });
    const index = page.candidates.indexOf(candidate);
    page.candidates[index] = { ...found, needs_detail: false };
  }
  render(); status('所选详情已读取，请核对正文后保存。');
});
async function results() {
  const data = await message({ type: 'status' }); $('results').replaceChildren();
  for (const entry of data.entries.slice(-10).reverse()) {
    const p = document.createElement('p');
    p.textContent = entry.state === 'confirmed' ? (entry.response.results ? entry.response.results.map(r => `${r.candidate_id}：${r.status}${r.error ? `（${r.error}）` : ''}`).join('\n') : `检查结果：${tips[entry.response.result] || ({changed:'来源已变化',unchanged:'无变化',failed:'检查失败'})[entry.response.result] || entry.response.result}`) : `${entry.state}：${tips[entry.error] || entry.error || '等待确认'}`;
    $('results').append(p);
  }
  for (const intent of data.intents.filter(x => x.state !== 'queued')) { const p = document.createElement('p'); p.textContent = `${intent.id}：${intent.state} ${tips[intent.error] || intent.error || ''}`; $('results').append(p); }
}
$('allow').onclick = run(async () => { const origin = new URL($('server').value).origin; await chrome.permissions.request({ origins: [origin + '/*'] }); status('授权完成后请点击登录。'); });
$('login').onclick = run(async () => {
  cfg = await message({ type: 'login', server: $('server').value, email: $('email').value.trim(), password: $('password').value });
  $('password').value = ''; await show(); status('已连接，请在原站打开内容后识别。');
});
$('scan').onclick = run(async () => {
  if (!tab || !/^https?:/.test(tab.url)) throw Error('unsupported');
  const allowed = await chrome.permissions.request({ origins: [new URL(tab.url).origin + '/*'] });
  if (!allowed) throw Error('permission_denied');
  page = await message({ type: 'scan', tabId: tab.id }); checked.clear(); render();
  status(page.candidates.length ? `识别到 ${page.candidates.length} 条候选，请勾选并预览。` : '当前页只有课程入口，请进入具体活动后识别。');
});
$('manual').onclick = run(async () => { const value = await message({ type: 'manual', tabId: tab.id }); page = { ...value, candidates: [value.target], navigation: [] }; render(); status('请确认预览中的完整元素范围，再勾选保存。'); });
$('save').onclick = run(async () => {
  const candidates = selected(); if (!candidates.length) return;
  const result = await message({ type: 'submit', tabId: tab.id, binding: page.binding, selected: candidates, enabled: $('monitor').checked });
  status(`已写入本地提交队列：${result.request_id}。尚未确认后端保存，可关闭弹窗后查询。`);
  $('save').disabled = true;
});
$('refresh').onclick = run(results);
$('retry').onclick = run(async () => { await message({ type: 'retry' }); await results(); });
$('wake').onclick = run(async () => { status('正在检查到期来源…'); await message({ type: 'wake' }); await results(); status('本次执行已结束，具体结果见提交记录及工作台。'); });
$('logout').onclick = run(async () => { await message({ type: 'logout' }); cfg = {}; await show(); });
$('open').onclick = () => chrome.tabs.create({ url: cfg.server + '/' });
async function show() {
  $('login-view').hidden = Boolean(cfg.uid); $('main-view').hidden = !cfg.uid;
  if (cfg.server) $('server').value = cfg.server;
  if (cfg.uid) { $('account').textContent = cfg.email; $('page-url').textContent = tab?.url || ''; await results(); }
}
try { [tab] = await chrome.tabs.query({ active: true, currentWindow: true }); cfg = await message({ type: 'config' }); await show(); status(''); }
catch (e) { status(e.message); }
