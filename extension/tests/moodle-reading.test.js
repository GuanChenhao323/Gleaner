// Sanitized DOM structures from observed layout shapes. No school requests or real content.
import test from 'node:test';
import assert from 'node:assert/strict';
import {rendered,parser,courses} from './scoped-fixture.mjs';
import {ExtractionPipeline} from '../extraction/pipeline.js';
import {event,timeline,support,columns,recent} from './dashboard-fixture.mjs';
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

test('Timeline in the real-shaped right column previews loaded events separately, never unrelated bodies',()=>{
  const p=rendered(columns(card(101,'测试课程'),timeline(event()+event(9002,{name:'测试测验',time:'00:00'}))+support+'<section class="block"><h5>Private files</h5><p id="unmatched">不相关正文</p></section>'));
  Object.defineProperty(p.document.querySelector('#unmatched'),'textContent',{get(){throw Error('unmatched body read');}});
  const r=result(p,'Timeline');assert.equal(r.candidates.length,2);assert.match(r.candidates[0].raw.text,/测试实验/);assert.ok(!JSON.stringify(r).includes('不相关正文'));assert.ok(!JSON.stringify(r).includes('support@example.test'));assert.equal(r.candidates[0].record_type,'timeline_event');assert.equal(r.save_mode,'timeline_summary');assert.equal(r.candidates[0].save_allowed,false);assert.equal(r.candidates[0].save_reason,'account_unknown');assert.equal(r.candidates[0].target,null);
  assert.equal(r.candidates[0].raw.fields.date_text,'Sunday, 15 November 2026');assert.equal(r.candidates[1].raw.fields.datetime_text,'00:00');assert.match(r.candidates[0].evidence[0].text,/Sunday, 15 November 2026/);assert.equal(r.coverage.regions[0].status,'matched');
});

test('a recognized left column cannot turn missing or unknown Timeline structures into false zero matches',()=>{
  assert.throws(()=>rendered(columns(card(101,'测试课程'),support)).read('Timeline'),/unsupported_region/);
  assert.throws(()=>rendered(columns(card(101,'测试课程'),timeline('<p>未知结构</p>'))).read('Timeline'),/unsupported_region/);
  const empty=result(rendered(columns(card(101,'测试课程'),timeline('<div data-region="empty-message">No activities</div>'))),'Timeline');assert.equal(empty.outcome.status,'no_match');
  assert.throws(()=>rendered(columns(card(101,'测试课程'),timeline('<div aria-busy="true">Loading</div>'))).read('Timeline'),/page_not_ready/);
});

test('Support is a bounded contact preview; requesting email does not imply a person or capture other fields',()=>{
  assert.equal(parser.parse('Moodle Support 的邮箱').kind,'auto');
  const p=rendered(columns(card(101,'测试课程'),support+timeline(event()))+'<footer>secret@example.test</footer>');
  assert.equal(p.read('Moodle Support 的邮箱').extraction.body_reads,0);
  const r=result(p,'Moodle Support 的邮箱'),c=r.candidates[0];assert.equal(c.raw.text,'邮箱：support@example.test');assert.deepEqual(c.raw.fields,{email:'support@example.test'});assert.equal(c.record_type,'contact_info');assert.equal(c.save_reason,'contact_preview_only');assert.equal(c.target,null);assert.ok(!JSON.stringify(r).includes('0000-1234'));assert.ok(!JSON.stringify(r).includes('测试实验'));assert.ok(!JSON.stringify(r).includes('secret@example.test'));
  assert.equal(result(p,'Moodle Support').candidates.length,1);assert.deepEqual(result(p,'Moodle Support 的职称').candidates[0].missing_fields,['role']);
});

test('admitting known right blocks never authorizes arbitrary asides, hidden blocks or navigation descendants',()=>{
  const hidden=support.replace('class="block block_html"','hidden class="block block_html"');
  assert.throws(()=>rendered(columns(card(101,'测试课程'),hidden)).read('Moodle Support'),/unsupported_region/);
  assert.throws(()=>rendered(columns(card(101,'测试课程'),support).replace('data-blockregion="side-pre"','data-blockregion="other"')).read('Moodle Support'),/unsupported_region/);
  const p=rendered(columns(card(101,'测试课程'),support.replace('<h6>','<nav>nav@example.test</nav><h6>')));assert.ok(!JSON.stringify(result(p,'Moodle Support')).includes('nav@example.test'));
});

test('activity primary title, type label and course context stay separate; literal assignment is not stripped',()=>{
  const p=rendered(columns(card(101,'测试课程')+recent(),''));
  const r=result(p,'assignment'),c=r.candidates[0];assert.equal(c.raw.title,'assignment');assert.equal(c.raw.fields.course,'SAMPLE COURSE(测试课程)');assert.equal(c.presentation.course_relation,'unconfirmed');assert.equal(c.presentation.region,'Recently accessed items');assert.match(c.evidence[0].text,/测试课程/);
  assert.equal(result(p,'测试课程').candidates.length,1);assert.equal(result(p,'测试课程的作业').candidates.length,0);
});

test('a bilingual exact alias wins over longer course names, while duplicate sections still ask for scope',()=>{
  const p=rendered(columns(card(101,'SAMPLE AI(人工智能) - DEMO-A')+card(202,'FOUNDATIONS(人工智能数学基础) - DEMO-B')+recent(7001,'assignment','FOUNDATIONS(人工智能数学基础) - DEMO-B'),''));
  const r=result(p,'人工智能');assert.deepEqual(r.candidates.map(c=>c.entity_id),['course:101']);assert.ok(!JSON.stringify(r).includes('assignment'));
  p.document.querySelector('#block-region-content').insertAdjacentHTML('beforeend',card(303,'SAMPLE AI(人工智能) - DEMO-C'));
  const choice=p.read('人工智能');assert.equal(choice.state,'needs_choice');assert.equal(choice.extraction.body_reads,0);
});

test('Moodle course-overview content marked navigation is admitted without authorizing other navigation',()=>{
  const overview='<section class="block block_myoverview"><h5>Course overview</h5><div class="block-myoverview" data-region="myoverview" role="navigation">'+card(101,'SAMPLE AI(人工智能) - DEMO-A','<nav>不可读导航</nav><div role="navigation">不可读菜单</div><form>不可读表单</form><p hidden>不可读隐藏</p>')+card(202,'FOUNDATIONS(人工智能数学基础) - DEMO-B')+'</div></section>';
  const p=rendered(columns(overview+recent(7001,'assignment','FOUNDATIONS(人工智能数学基础) - DEMO-B'),'')),r=result(p,'人工智能');
  assert.deepEqual(r.candidates.map(c=>c.entity_id),['course:101']);assert.ok(!JSON.stringify(r).includes('不可读'));assert.equal(r.coverage.course_index.indexed_courses,2);
  const unrecognized=rendered(columns(overview.replace('class="block-myoverview"','class="other-content"'),''));assert.throws(()=>result(unrecognized,'人工智能'),/unsupported_dom/);
});

test('native course relations permit grouped activity previews; ambiguous recent context cannot replace them',()=>{
  const p=rendered(columns(card(101,'测试课程')+recent(7001,'assignment','测试课程','101'),timeline(event(9001,{courseId:'101'}))));
  const r=result(p,'测试课程');assert.deepEqual(r.candidates.map(c=>c.presentation.group),['courses','assignments','assignments']);assert.equal(r.candidates[1].raw.title,'assignment');assert.ok(r.candidates.every(c=>c.presentation.course_relation==='native'));
  const explicit=result(p,'测试课程的作业');assert.equal(explicit.candidates.length,2);assert.ok(explicit.candidates.every(c=>!c.save_allowed));assert.ok(!explicit.candidates.some(c=>c.record_type==='course_entry'));
});

test('Timeline supports non-assignment activity links without falsely labeling them as assignments',()=>{
  const p=rendered(columns('',timeline(event().replaceAll('/mod/assign/view.php','/mod/quiz/view.php'))));
  const c=result(p,'Timeline').candidates[0];assert.equal(c.entity_id,null);assert.equal(c.record_type,'timeline_event');assert.equal(c.save_allowed,false);
});

test('distinct loaded timeline rows sharing an activity URL are not merged into one invented event identity',()=>{
  const p=rendered(columns('',timeline(event(9001,{name:'开放时间',time:'08:00'})+event(9001,{name:'提交截止',time:'23:59'}))));
  const r=result(p,'Timeline');assert.equal(r.candidates.length,2);assert.ok(r.candidates.every(c=>c.entity_id===null && !c.target));assert.deepEqual(r.candidates.map(c=>c.raw.fields.datetime_text),['08:00','23:59']);
});

test('unexpected preview metadata cannot turn a timeline summary into a saveable assignment',()=>{
  const p=rendered(columns('',timeline(event()))),intent=parser.parse('Timeline'),snapshot=p.read('Timeline');
  snapshot.records[0].complete=true;delete snapshot.records[0].preview_reason;assert.throws(()=>pipeline.extract(snapshot,intent),/invalid_snapshot/);
  snapshot.records[0].complete=false;snapshot.records[0].preview_reason='timeline_preview_only';snapshot.records[0].presentation.group='invented';assert.throws(()=>pipeline.extract(snapshot,intent),/invalid_snapshot/);
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

test('detail keeps the labelled due date, own submission summary and attachment link',()=>{
  const p=rendered(`<main><h2>Lab11</h2><div class="activity-dates">
    <div><strong>Opened:</strong> Thursday, 19 November 2026, 12:00 AM</div>
    <div><strong>Due:</strong> Thursday, 31 December 2026, 12:00 AM</div></div>
    <table><tr><th>Submission status</th><td>No attempt</td></tr><tr><th>Grading status</th><td>Not graded</td></tr>
    <tr><th>Time remaining</th><td>41 days 5 hours</td></tr><tr><th>Submission comments</th><td>private comment</td></tr></table>
    <a href="/pluginfile.php/1/mod_assign/introattachment/0/demo.docx">demo.docx</a></main>`,
    'https://moodle.must.edu.mo/mod/assign/view.php?id=1101');
  p.document.body.setAttribute('data-userid','7');
  assert.equal(result(p,'Lab 1').candidates.length,0);
  const c=result(p,'Lab 11').candidates[0];
  assert.equal(c.save_allowed,true);
  assert.equal(c.raw.fields.due_text,'Thursday, 31 December 2026, 12:00 AM');
  assert.equal(c.raw.fields.submission_status,'No attempt');
  assert.equal(c.raw.fields.grading_status,'Not graded');
  assert.equal(c.raw.fields.time_remaining,'41 days 5 hours');
  assert.match(c.raw.text,/未读取正文.*demo.docx/);
  assert.doesNotMatch(c.raw.text,/private comment|19 November/);
});

test('Moodle adapter does not expand into unrelated authenticated route types',()=>{
  assert.throws(()=>rendered(root(card(101,'测试课程')),'https://moodle.must.edu.mo/grade/report/user/index.php').read('测试课程'),/unsupported/);
});
