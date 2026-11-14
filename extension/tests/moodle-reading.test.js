// Sanitized DOM structures from observed layout shapes. No school requests or real content.
import test from 'node:test';
import assert from 'node:assert/strict';
import {rendered,parser,courses} from './scoped-fixture.mjs';
import {ExtractionPipeline} from '../extraction/pipeline.js';
const pipeline=new ExtractionPipeline();
const root=body=>`<section id="region-main"><div role="main"><aside id="block-region-content" class="block-region" data-blockregion="content">${body}</aside></div></section>`;
const card=(id,name,body='')=>`<div class="list-group-item"><a class="aalink coursename" href="/course/view.php?id=${id}">${name}</a><div class="progress" role="progressbar" aria-valuenow="40">40% complete</div>${body}</div>`;
const result=(p,q,choice)=>pipeline.extract(p.read(q,choice),parser.parse(q));

test('observed content aside contains readable course cards; ordinary keyword returns a bounded entry preview',()=>{
  const p=rendered(root(card(101,'测试课程')+card(202,'其他课程')));
  const r=result(p,'测试课程');assert.equal(r.outcome.status,'matched');assert.equal(r.candidates.length,1);
  const c=r.candidates[0];assert.equal(c.record_type,'course_entry');assert.match(c.raw.text,/40% complete/);assert.ok(!c.raw.text.includes('其他课程'));assert.equal(c.save_reason,'navigation_only');assert.equal(c.target,null);
});

test('allowing content aside does not admit hidden nodes, nested nav/form/footer or a navigation aside',()=>{
  const p=rendered(root(card(101,'测试课程','<nav>不可读导航</nav><form>不可读表单<input value="secret"></form><footer>不可读页脚</footer><p hidden>不可读隐藏</p>'))+'<aside><a href="/course/view.php?id=909">旁边课程</a></aside>');
  const r=result(p,'测试课程');assert.ok(!JSON.stringify(r).includes('不可读'));assert.ok(!JSON.stringify(r).includes('secret'));
  assert.equal(result(p,'旁边课程').outcome.status,'no_match');
  const a=p.document.querySelector('a');assert.equal(new p.context.CampusScoped.DomAccess().visible(a),false);
});

test('aside without the verified content marker remains unsupported, not a false zero match',()=>{
  const p=rendered('<section id="region-main"><aside id="block-region-content"><a href="/course/view.php?id=101">测试课程</a></aside></section>');
  assert.throws(()=>p.read('测试课程'),/unsupported_dom/);
});

test('CSS hidden ancestors stay excluded even when the content region is admitted',()=>{
  const p=rendered(root(card(101,'测试课程')+`<div class="display-none">${card(202,'隐藏课程')}</div>`));
  p.context.getComputedStyle=n=>({display:n.classList.contains('display-none')?'none':'block',visibility:'visible'});
  assert.equal(result(p,'隐藏课程').outcome.status,'no_match');
});

test('bare course name previews course and loaded activities; explicit assignments remains exactly two',()=>{
  const p=rendered(root(courses()));p.document.body.setAttribute('data-userid','7');
  const ordinary=result(p,'网络编程');assert.deepEqual(ordinary.candidates.map(c=>c.record_type),['course_entry','assignment','assignment']);
  assert.ok(!ordinary.candidates[0].raw.text.includes('原始要求'));
  const explicit=result(p,'网络编程的作业');assert.equal(explicit.candidates.length,2);assert.ok(explicit.candidates.every(c=>c.save_allowed));assert.ok(!JSON.stringify(explicit).includes('数据科学'));
});

test('assignment title keyword also works without pretending it is a course name',()=>{
  const p=rendered(root(courses()));const r=result(p,'1102');assert.equal(r.candidates.length,1);assert.equal(r.candidates[0].entity_id,'assignment:1102');
});

test('Timeline heading selects only the loaded block, never unrelated block bodies',()=>{
  const p=rendered(root('<section class="block block_timeline" id="inst1"><h5>Timeline</h5><p>脱敏活动 A</p></section><section class="block" id="inst2"><h5>其他版块</h5><p id="unmatched">不相关正文</p></section>'));
  Object.defineProperty(p.document.querySelector('#unmatched'),'textContent',{get(){throw Error('unmatched body read');}});
  const r=result(p,'Timeline');assert.equal(r.candidates.length,1);assert.match(r.candidates[0].raw.text,/脱敏活动 A/);assert.ok(!JSON.stringify(r).includes('不相关正文'));assert.equal(r.candidates[0].record_type,'page_section');assert.equal(r.candidates[0].save_reason,'section_preview_only');assert.equal(r.candidates[0].target,null);
});

test('a descendant activity heading cannot cause the enclosing multi-activity section to be read',()=>{
  const p=rendered('<main><section id="week1"><div class="activity"><h3>目标活动</h3><p>目标正文</p></div><div class="activity"><h3>其他活动</h3><p>其他正文</p></div></section><a href="/course/view.php?id=101">测试课程</a></main>');
  const r=result(p,'目标活动');assert.equal(r.candidates.length,0);assert.ok(!JSON.stringify(r).includes('其他正文'));
});

test('course cards spanning multiple courses fall back to the selected native link, not a broad container',()=>{
  const p=rendered(root('<div class="list-group-item"><a href="/course/view.php?id=101">测试课程</a><a href="/course/view.php?id=202">无关课程</a><p>无关容器正文</p></div>'));
  const c=result(p,'测试课程').candidates[0];assert.equal(c.raw.text,'测试课程');
});

test('recognized zero, course navigation, and unrecognized DOM have distinct outcomes',()=>{
  const p=rendered(root(card(101,'测试课程')));
  assert.equal(result(p,'不存在的课程').outcome.status,'no_match');
  const navigation=result(p,'测试课程的作业');assert.equal(navigation.outcome.status,'navigation_required');assert.equal(navigation.navigation.length,1);
  assert.throws(()=>rendered('<main><p>未知页面内容</p></main>').read('测试课程'),/unsupported_dom/);
});

test('course ambiguity is resolved before any card or assignment body read',()=>{
  const p=rendered(root(card(101,'测试课程')+card(404,'测试课程 重修班')));
  const pending=p.read('测试课程');assert.equal(pending.state,'needs_choice');assert.equal(pending.extraction.body_reads,0);
  const r=result(p,'测试课程','404');assert.equal(r.candidates.length,1);assert.equal(r.candidates[0].entity_id,'course:404');assert.throws(()=>p.read('测试课程','999'),/invalid_choice/);
});

test('visible descendants do not leak hidden text into matched titles',()=>{
  const p=rendered(root('<a href="/course/view.php?id=101">测试课程<span hidden>伪关键词</span></a>'));
  assert.equal(result(p,'伪关键词').outcome.status,'no_match');
});

test('known busy Moodle region is not misreported as a recognized empty result',()=>{
  assert.throws(()=>rendered(root('<div aria-busy="true">loading courses</div>')).read('测试课程'),/page_not_ready/);
});

test('a single dashboard course link cannot claim ownership of unscoped timeline assignments',()=>{
  const p=rendered(root(card(101,'测试课程')+'<section class="block block_timeline"><h5>Timeline</h5><li class="activity"><a href="/mod/assign/view.php?id=9001">其他课的作业</a><div class="activity-description">不能错误归入目标课程</div></li></section>'));
  assert.equal(result(p,'测试课程的作业').candidates.length,0);
  assert.ok(!JSON.stringify(result(p,'测试课程')).includes('不能错误归入目标课程'));
});

test('on a native course page the bare course name previews bounded loaded sections',()=>{
  const p=rendered('<main><h1>测试课程</h1><section id="section-0"><h3>课程说明</h3><p>本课程当前已加载说明</p></section><section id="section-1"><h3>第一周</h3><p>本周学习资料</p></section><aside>无关侧栏</aside></main>','https://moodle.must.edu.mo/course/view.php?id=101');
  const r=result(p,'测试课程');assert.equal(r.candidates.filter(c=>c.record_type==='page_section').length,2);assert.ok(!JSON.stringify(r).includes('无关侧栏'));
});

test('course card preview prefers the bounded outer card so loaded progress is retained',()=>{
  const p=rendered(root('<div class="list-group-item"><div data-region="course-content"><a href="/course/view.php?id=101">测试课程</a></div><p>已完成 40%</p></div>'));
  assert.match(result(p,'测试课程').candidates[0].raw.text,/40%/);
});

test('a known course-overview header with a visible loading placeholder still waits for content',()=>{
  assert.throws(()=>rendered(root('<section class="block block_myoverview" id="inst1"><h5>Course overview</h5><div data-region="loading-placeholder">Loading</div></section>')).read('测试课程'),/page_not_ready/);
});

test('on assignment detail a literal activity-title query reads only its description',()=>{
  const p=rendered('<main><h2>Lab10</h2><div class="activity-description">合成作业原文</div><table><tr><td>不属于原始要求的个人状态</td></tr></table></main>','https://moodle.must.edu.mo/mod/assign/view.php?id=1101');
  const r=result(p,'Lab10');assert.equal(r.candidates.length,1);assert.equal(r.candidates[0].raw.text,'合成作业原文');assert.ok(!JSON.stringify(r).includes('个人状态'));
});

test('full native breadcrumb title resolves course names when link text is only a course code',()=>{
  const p=rendered('<nav class="breadcrumb"><a title="测试课程 完整名称" href="/course/view.php?id=101">DEMO-CODE</a></nav><main><h2>Lab10</h2><div class="activity-description">合成作业正文</div></main>','https://moodle.must.edu.mo/mod/assign/view.php?id=1101');
  assert.equal(result(p,'测试课程的作业').candidates.length,1);
});

test('attachment-only assignment previews loaded names/links without downloading or claiming complete text',()=>{
  const p=rendered('<main><h2>Lab10</h2><a href="/pluginfile.php/1/mod_assign/introattachment/0/demo.docx?forcedownload=1">demo.docx</a><p>个人提交状态不能提取</p></main>','https://moodle.must.edu.mo/mod/assign/view.php?id=1101');
  const c=result(p,'Lab10').candidates[0];assert.match(c.raw.text,/demo.docx/);assert.equal(c.save_reason,'attachments_only');assert.equal(c.save_allowed,false);assert.equal(c.target,null);assert.ok(!c.raw.text.includes('个人提交状态'));
});

test('Moodle adapter does not expand into unrelated authenticated route types',()=>{
  assert.throws(()=>rendered(root(card(101,'测试课程')),'https://moodle.must.edu.mo/grade/report/user/index.php').read('测试课程'),/unsupported/);
});
