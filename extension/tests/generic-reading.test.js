import test from 'node:test';
import assert from 'node:assert/strict';
import {rendered} from './scoped-fixture.mjs';
import {LiteralIntentParser} from '../extraction/intent.js';
import {ExtractionPipeline} from '../extraction/pipeline.js';
import {DomPageReader} from '../extraction/readers.js';
const url='https://previously-unregistered.example.test/inbox#loaded';
const extract=(page,query,scope='content')=>{
  const intent=new LiteralIntentParser().parse(query,scope);
  return new ExtractionPipeline().extract(JSON.parse(JSON.stringify(page.context.CampusScoped.execute({intent}))),intent);
};

test('unregistered domains match body phrases across nested inline text, preserving literal school words',()=>{
  const page=rendered('<main><p>奖学金<span>公告</span>：今天开放申请。</p><p>无关的完整正文绝不返回。</p></main>',url);
  const r=extract(page,'奖学金公告');assert.equal(r.source,'generic');assert.equal(r.candidates.length,1);assert.match(r.candidates[0].raw.text,/今天/);assert.ok(!JSON.stringify(r).includes('无关的完整正文'));assert.equal(r.account.state,'unknown');assert.equal(r.candidates[0].entity_id,null);
  assert.equal(extract(page,'今天').candidates.length,1);
});

test('mail-shaped list rows and table rows stay independent without consuming unchecked neighbours',()=>{
  for(const domain of [url,'https://another.example.org/list']) {
    const page=rendered('<div role="grid"><div role="row"><div>林同学</div><div>项目会议 <b>改到周五</b></div></div><div role="row"><span>林同学</span><span>材料已补充</span></div><div role="row">其他人的隐私正文</div></div>',domain);
    const r=extract(page,'林同学');assert.equal(r.candidates.length,2);assert.ok(r.candidates.every(c=>c.context.boundary==='table_row'));assert.ok(!JSON.stringify(r).includes('其他人的隐私正文'));
  }
  const p=rendered('<table><tr><td>项目</td><td>网络编程</td><td>星期一</td></tr><tr><td>其他课程</td></tr></table>',url);
  assert.match(extract(p,'网络编程').candidates[0].raw.text,/星期一/);
});

test('navigation and aside are readable but hidden, editable and form values never participate',()=>{
  const p=rendered('<aside><p>办公室联系信息</p></aside><nav><a href="/news">办公室新闻</a></nav><p hidden>办公室隐藏</p><p style="display:none">办公室不显示</p><input value="办公室密码"><textarea>办公室草稿</textarea><div contenteditable>办公室正在编辑</div><script>办公室脚本</script>',url);
  const r=extract(p,'办公室');assert.equal(r.candidates.length,2);assert.ok(!/隐藏|不显示|草稿|正在编辑|脚本|密码/.test(r.candidates.map(c=>c.raw.text).join('')));
});

test('title-only scope selects heading/link hits; no-match never returns whole page',()=>{
  const p=rendered('<article><h2>课程通知</h2><p>网络编程正文</p></article><li><a href="/x">网络编程标题</a><span>摘要内容</span></li>',url);
  assert.equal(extract(p,'网络编程').candidates.length,2);
  const r=extract(p,'网络编程','title');assert.equal(r.candidates.length,1);assert.match(r.candidates[0].raw.text,/摘要内容/);
  assert.equal(extract(p,'不存在的条件').outcome.status,'no_match');
});

test('open shadow DOM is readable, iframe content is explicitly excluded and reported',()=>{
  const p=rendered('<main><div id="host"></div><iframe src="/private"></iframe></main>',url);
  p.document.querySelector('#host').attachShadow({mode:'open'}).innerHTML='<p>网络编程 Shadow 片段</p>';
  const r=extract(p,'网络编程');assert.equal(r.candidates.length,1);assert.match(r.candidates[0].evidence[0].locator,/::shadow/);assert.equal(r.coverage.open_shadow_roots,1);assert.equal(r.coverage.frames_excluded,1);
});

test('loading, visible password gate and oversized matches fail explicitly',()=>{
  assert.throws(()=>extract(rendered('<main aria-busy="true">正在加载</main>',url),'加载'),/page_not_ready/);
  assert.throws(()=>extract(rendered('<form><input type="password"></form><p>登录</p>',url),'登录'),/need_login/);
  assert.throws(()=>extract(rendered('<p>目标'+ 'x'.repeat(20001)+'</p>',url),'目标'),/content_too_large/);
  assert.throws(()=>extract(rendered('<ul>'+Array.from({length:101},(_,i)=>`<li>目标 ${i}</li>`).join('')+'</ul>',url),'目标'),/candidate_limit/);
});

test('generic fallback cannot bypass a known school adapter preview or unsupported structure',()=>{
  assert.throws(()=>extract(rendered('<p>目标内容</p>','https://moodle.must.edu.mo/my/'),'目标'),/unsupported_dom/);
});

test('bare text and mixed container hits cannot authorize the entire document',()=>{
  for(const html of ['目标正文<p>不能一起采集的段落</p>','<main>目标正文<p>不能一起采集的段落</p></main>','<div>目标正文<div>不能一起采集的段落</div></div>']) {
    const r=extract(rendered(html,url),'目标');assert.equal(r.candidates.length,1);assert.equal(r.candidates[0].raw.text,'目标正文');assert.ok(!JSON.stringify(r).includes('不能一起采集'));
  }
});

test('browser policy refusal, missing host access and closed page have distinct readable failures',async()=>{
  for(const [message,code] of [['The extensions gallery cannot be scripted','restricted_page'],['Cannot access contents of the page. Extension manifest must request permission','permission_denied'],['No tab with id: 999','page_read_failed']]) {
    const reader=new DomPageReader({scripting:{executeScript:async()=>{throw Error(message);}}});await assert.rejects(reader.invoke(999,'execute'),new RegExp(code));
  }
});
