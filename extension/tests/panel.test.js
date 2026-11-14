import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {panelHarness,capture,declareSource} from './panel-fixture.mjs';
import {ReceiptPresenter} from '../ui/receipt-view.js';

const run=(name,fn)=>test(name,async()=>{const h=await panelHarness();try{await fn(h);}finally{h.dispose();}});
run('single popup shows real connection, compact page context and no separate workspace entry',async h=>{
  assert.equal(h.view.$('connection-status').textContent,'工作台已连接');
  assert.ok(!h.view.$('page').textContent.includes('https://'));assert.equal(h.view.$('page-url').hidden,true);
  assert.equal(h.view.$('source-binding').hidden,true);assert.equal(h.messages.filter(m=>m.type==='extract.start').length,0);
  assert.equal(h.document.querySelectorAll('[data-scope]').length,2);assert.equal(h.view.$('large'),null);
  assert.equal(fs.existsSync(new URL('../workspace.html',import.meta.url)),false);
  h.view.$('connection-toggle').onclick();assert.equal(h.view.$('connection').open,true);
  await h.controller.login();assert.equal(h.view.$('login-fields').hidden,false);
  assert.equal(h.messages.filter(m=>m.type==='login').length,0);
  h.view.$('page-more').onclick();assert.match(h.view.$('page-url').textContent,/unregistered/);
});
run('private source requires explicit confirmation; full preview stays local until one explicit save',async h=>{
  await capture(h);assert.equal(h.document.querySelectorAll('.result-card').length,2);
  assert.equal(h.messages.filter(m=>m.type==='extract.save').length,0);
  h.view.select('source-kind','labeled');h.view.$('source-kind').onchange();
  h.view.$('source-label').value='学';h.view.$('source-label').oninput();assert.equal(h.view.$('source-label-field').hidden,false);assert.equal(h.view.$('save').disabled,true);
  h.view.$('source-label').value='学校邮箱';h.view.$('source-label').oninput();await h.controller.confirmBinding();
  assert.equal(h.view.$('source-label-field').hidden,true);assert.equal(h.view.$('binding-value').textContent,'学校邮箱');
  const full=h.document.querySelector('.full-fragment');full.open=true;full.dispatchEvent(new h.document.defaultView.Event('toggle'));
  assert.equal(full.querySelector('summary').textContent,'收起');
  assert.equal(full.querySelector('pre').textContent,h.controller.task.result.candidates[0].raw.text);
  await h.controller.refresh();assert.equal(h.document.querySelector('.full-fragment'),full);assert.equal(full.open,true);
  await h.controller.save();assert.match(h.view.$('results').textContent,/已保存为 1/);
  const receipt=h.view.$('results').querySelector('details');receipt.open=true;await h.controller.refresh();
  assert.equal(h.view.$('results').querySelector('details'),receipt);assert.equal(receipt.open,true);
  assert.equal(h.messages.filter(m=>m.type==='extract.save').length,1);
  assert.deepEqual(Object.keys(h.messages.find(m=>m.type==='extract.save')).sort(),['id','query','source_binding','type']);
});
run('save reserves before awaiting browser APIs; double click and clear cannot change submission',async h=>{
  await capture(h);await declareSource(h);
  let release;h.browser.tabs.get=()=>new Promise(r=>release=r);
  const first=h.controller.save(),second=h.controller.save();assert.equal(h.view.$('clear-query').disabled,true);assert.equal(h.view.$('query').disabled,true);
  release({id:1,url:h.controller.form.url});await Promise.all([first,second]);assert.equal(h.messages.filter(m=>m.type==='extract.save').length,1);
});
run('page URL/hash changes invalidate old preview and source declaration without deleting old tasks',async h=>{
  await capture(h);await declareSource(h);const old=h.controller.task.id;
  h.setTab({id:1,url:'https://unregistered.example.test/inbox#other',title:'新视图'});await h.controller.checkPage();
  assert.equal(h.controller.task,null);assert.equal(h.view.$('save').disabled,true);assert.equal(h.view.source.ready(),false);assert.ok(h.ctx.tasks.has(old));assert.match(h.view.$('status').textContent,/已变化/);
});
run('lost save acknowledgement is unconfirmed; reopening queries original saved request without rereading',async h=>{
  await capture(h);await declareSource(h);const id=h.controller.task.id;h.ctx.loseSaveReply=true;
  await assert.rejects(h.controller.save(),/worker_timeout/);assert.match(h.view.$('results').textContent,/尚未确认/);assert.equal(h.view.$('save').hidden,true);
  const reopened=await h.boot();assert.equal(reopened.controller.task.id,id);assert.match(reopened.view.$('results').textContent,/已保存为 1/);
  assert.equal(h.messages.filter(m=>m.type==='extract.start').length,1);assert.equal(h.messages.filter(m=>m.type==='extract.save').length,1);
});
run('lost save message before worker acceptance retries the same task and frozen preview',async h=>{
  await capture(h);await declareSource(h);const id=h.controller.task.id;
  let lose=true;h.ctx.onMessage=m=>{if(m.type==='extract.save' && lose){lose=false;throw Error('worker_timeout');}};
  await assert.rejects(h.controller.save(),/worker_timeout/);assert.equal(h.view.$('retry').hidden,false);
  await h.view.$('retry').onclick();assert.match(h.view.$('results').textContent,/已保存为 1/);
  assert.deepEqual(h.messages.filter(m=>m.type==='extract.save').map(m=>m.id),[id,id]);
});
run('expired session re-login keeps same-owner task and confirms original submission',async h=>{
  await capture(h);await declareSource(h);await h.controller.save();const id=h.controller.task.id;
  h.ctx.entries.get(id).state='auth_required';h.ctx.entries.get(id).error='unauthorized';await h.controller.refresh();
  assert.match(h.view.$('results').textContent,/登录已失效/);assert.equal(h.view.$('login-fields').hidden,false);
  h.view.$('email').value='demo@example.test';h.view.$('password').value='fixture password';await h.controller.login();
  assert.equal(h.controller.task.id,id);assert.equal(h.view.$('password').value,'');assert.match(h.view.$('results').textContent,/已保存/);assert.equal(h.messages.filter(m=>m.type==='extract.save').length,1);
});
run('failed connection switch shows inline login error, clears password and retains original owner preview',async h=>{
  await capture(h);await declareSource(h);const id=h.controller.task.id;
  await h.controller.login();h.view.$('password').value='incorrect fixture password';
  h.ctx.onMessage=m=>{if(m.type==='login')throw Error('bad_credentials');};
  await assert.rejects(h.controller.login(),/bad_credentials/);
  assert.equal(h.view.$('connection-error').hidden,false);assert.match(h.view.$('connection-error').textContent,/邮箱或密码错误/);
  assert.equal(h.view.$('password').value,'');assert.equal(h.controller.task.id,id);assert.equal(h.controller.cfg.uid,1);
});
run('owner switching hides old content and labels; late connection checks cannot restore previous account',async h=>{
  await capture(h);await declareSource(h);let resolve;
  h.ctx.onMessage=(m,ctx)=>{if(m.type==='connection.check' && ctx.cfg.uid===1)return new Promise(r=>resolve=r);};
  const stale=h.controller.checkConnection();await new Promise(r=>setImmediate(r));h.ctx.cfg={...h.ctx.cfg,uid:2,email:'other@example.test'};
  await h.controller.changeOwner(h.ctx.cfg);resolve({state:'connected',uid:1,email:'demo@example.test'});await stale;
  assert.equal(h.view.$('account').textContent,'other@example.test');assert.equal(h.document.querySelectorAll('.result-card').length,0);assert.equal(h.view.source.ready(),false);assert.equal(h.controller.task,null);
});
run('history stays read-only for extraction and never overwrites current unsubmitted conditions',async h=>{
  await capture(h);const t=h.controller.task;h.view.$('query').value='当前未提交的新条件';h.controller.edit();
  await h.controller.openHistory(t);assert.equal(h.view.$('capture').disabled,true);assert.equal(h.view.$('query').disabled,true);assert.equal(h.view.$('source-mode').textContent,'历史预览');
  h.view.select('source-kind','public');h.view.$('source-kind').onchange();await new Promise(r=>setImmediate(r));
  await h.controller.returnCurrent();assert.equal(h.view.$('query').value,'当前未提交的新条件');assert.equal(h.controller.task,null);
});
run('pending error retains preview, offers targeted retry and never shows success early',async h=>{
  await capture(h);await declareSource(h);await h.controller.save();const id=h.controller.task.id;
  const entry=h.ctx.entries.get(id);entry.state='pending';entry.error='backend_timeout';await h.controller.refresh();
  assert.match(h.view.$('results').textContent,/尚未确认/);assert.equal(h.view.$('continue').hidden,true);
  await h.view.$('retry').onclick();assert.match(h.view.$('results').textContent,/已保存/);assert.equal(h.messages.findLast(m=>m.type==='retry').request_id,id);assert.equal(h.messages.filter(m=>m.type==='extract.start').length,1);
});
run('zero match and unsupported pages never expose a source picker or enabled save',async h=>{
  await capture(h);const t=structuredClone(h.controller.task);t.id='zero-match-task';t.result.candidates=[];t.result.outcome={status:'no_match'};h.view.task(t);
  assert.equal(h.view.$('source-binding').hidden,true);assert.equal(h.view.$('save').disabled,true);assert.match(h.view.$('preview').textContent,/匹配 0 条/);
  h.setTab({id:1,url:'chrome://extensions/',title:'扩展程序'});await h.controller.checkPage();assert.equal(h.view.$('capture').disabled,true);assert.equal(h.view.$('source-mode').textContent,'页面受限');
});
run('rejected read preserves its actual reason across polling and reopening without querying missing drafts',async h=>{
  h.ctx.onMessage=m=>{if(m.type==='extract.start')throw Error('draft_limit');};
  await assert.rejects(capture(h),/draft_limit/);assert.equal(h.controller.form.taskId,null);
  await h.controller.poll();assert.match(h.view.$('status').textContent,/容量上限/);
  const reopened=await h.boot();assert.match(reopened.view.$('status').textContent,/容量上限/);
  assert.equal(reopened.view.$('query').value,'项目会议');assert.equal(h.messages.filter(m=>m.type==='extract.get').length,0);
});
run('known campus page replaces generic scope choices with truthful specialized scope',async h=>{
  h.setTab({id:1,url:'https://moodle.must.edu.mo/my/',title:'Dashboard'});await h.controller.checkPage();
  assert.equal(h.view.$('scope-options').hidden,true);assert.equal(h.view.$('special-scope').hidden,false);
});
test('empty/malformed and partial receipts cannot produce whole-batch success',()=>{
  const p=new ReceiptPresenter();assert.equal(p.present({state:'confirmed',response:{}}).state,'unconfirmed');
  assert.equal(p.present({state:'confirmed',response:{results:[{status:'new',item_id:0}]}}).state,'unconfirmed');
  const partial=p.present({state:'confirmed',response:{results:[{status:'new',item_id:1},{status:'failed',candidate_id:'b',error:'invalid_snapshot'}]}});
  assert.equal(partial.state,'partial');assert.match(partial.title,/成功 1，失败 1/);
});
