import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {parseHTML} from 'linkedom';
import english from '../ui/locales/en.js';
import {t, setLanguage, getLanguage, staticLocalizer, initializeLanguage, retranslate} from '../ui/i18n.js';
import {CaptureView} from '../ui/view.js';
import {errorText} from '../ui/errors.js';
import {ReceiptPresenter} from '../ui/receipt-view.js';
const popup = () => parseHTML(fs.readFileSync(new URL('../popup.html', import.meta.url), 'utf8')).document;

test('English catalog preserves placeholders and static copy round-trips without touching user inputs', () => {
  for (const [key, value] of Object.entries(english)) {
    assert.deepEqual((key.match(/\{\d+\}/g) || []).sort(), (value.match(/\{\d+\}/g) || []).sort(), key);
  }
  const document = popup(), localize = staticLocalizer(document);
  document.getElementById('query').value = '网络编程的作业';
  document.getElementById('intent-text').value = '输入条件后，结果会出现在这里。';
  const before = document.body.textContent;
  setLanguage('en'); localize();
  assert.equal(document.documentElement.lang, 'en');
  assert.equal(document.getElementById('capture').textContent, 'Extract');
  assert.equal(document.getElementById('query').placeholder, 'Enter a course, keyword or phrase');
  assert.equal(document.getElementById('connection-toggle').getAttribute('aria-label'), 'Connection settings');
  assert.equal(document.getElementById('intent-text').value, '输入条件后，结果会出现在这里。');
  setLanguage('zh-CN'); localize();
  assert.equal(document.body.textContent, before);
  assert.equal(document.getElementById('query').value, '网络编程的作业');
});

test('English dynamic previews and errors preserve captured Chinese content and save policy', () => {
  setLanguage('en');
  const document = popup(), view = new CaptureView(document);
  view.config({uid: 1, email: 'test@example.com'}); view.ready(true);
  document.getElementById('query').value = '课程';
  const task = {id: 'test', schema_version: 2, state: 'succeeded', result: {source: 'moodle', candidates: [{
    record_type: 'assignment', raw: {title: '提取', text: '原文必须保留：网络编程实验', fields: {due_text: '明天'}},
    save_allowed: true, url: 'https://moodle.must.edu.mo/mod/assign/view.php?id=1', evidence: []
  }]}};
  view.task(task);
  assert.equal(document.querySelector('.result-card h3').textContent, '提取');
  assert.match(document.getElementById('preview').textContent, /原文必须保留：网络编程实验/);
  assert.match(document.getElementById('preview').textContent, /Due date：明天/);
  assert.equal(document.getElementById('save').textContent, 'Save matches (1)');
  assert.equal(document.getElementById('save').disabled, false);
  assert.match(errorText('backend_unavailable'), /local backend is unavailable/);
  assert.equal(errorText('new_error'), 'Operation incomplete: new_error');
  const message = t`来源账号：${'学生甲'} · 已核对。后台能力需在工作台测试。`;
  setLanguage('zh-CN');
  assert.equal(retranslate(message), '来源账号：学生甲 · 已核对。后台能力需在工作台测试。');
});

test('saved locale overrides browser language and changing locale persists without losing fields', async () => {
  const document = popup(), select = document.getElementById('language');
  // linkedom exposes a getter-only select.value; Chrome provides a setter.
  Object.defineProperty(select, 'value', {writable: true, value: 'zh-CN'});
  const saved = {ui_language: 'en'};
  await initializeLanguage(document, {get: async () => saved, set: async value => Object.assign(saved, value)}, 'zh-CN');
  assert.equal(getLanguage(), 'en');
  assert.equal(select.value, 'en');
  document.getElementById('password').value = 'unsent password';
  const changed = new Promise(resolve => document.addEventListener('languagechange', resolve, {once:true}));
  select.value = 'zh-CN'; select.dispatchEvent(new document.defaultView.Event('change'));
  await changed;
  assert.equal(saved.ui_language, 'zh-CN');
  assert.equal(document.getElementById('password').value, 'unsent password');
  assert.equal(document.getElementById('capture').textContent, '提取');
});

test('English timeline receipt identifies summary material', () => {
  setLanguage('en');
  const result = new ReceiptPresenter().present({state:'confirmed', response:{capture_type:'timeline_summary',results:[{status:'new',item_id:1,capture_id:'c',fragment_count:2}]}});
  assert.equal(result.title, 'Saved as 1 activity summary');
  setLanguage('zh-CN');
});
