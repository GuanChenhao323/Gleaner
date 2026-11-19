import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import Ajv from 'ajv/dist/2020.js';
import {parseHTML} from 'linkedom';
import {resolveTemplates,projectPage} from '../templates/resolve.js';

const read=name=>JSON.parse(readFileSync(new URL('../templates/'+name,import.meta.url),'utf8'));
const catalog=read('catalog.json');
function capture(purpose,html,{url='https://example.com/show',selection='',rules=catalog}={}) {
  const {document}=parseHTML(html);
  const location=new URL(url);
  const templates=resolveTemplates(rules,purpose,location.hostname);
  return runInNewContext('('+projectPage.toString()+')(templates,purpose)',{
    URL,location,document,window:{getSelection:()=>selection},templates,purpose
  });
}
test('packaged rules conform to the shared schema',()=>{
  const validate=new Ajv().compile(read('schema.json'));
  assert.ok(validate(catalog),JSON.stringify(validate.errors));
});
test('same page supports distinct user intents and link-only reference',()=>{
  const html='<title>展览</title><time data-booking-deadline datetime="2027-03-01T18:00"></time><time itemprop="startDate" datetime="2027-03-03T09:00"></time>';
  assert.equal(capture('todo',html).date,'2027-03-01T18:00');
  assert.equal(capture('event',html).date,'2027-03-03T09:00');
  assert.equal(capture('reference',html).date,'');
  assert.equal(capture('reference',html,{selection:'展览介绍'}).text,'展览介绍');
  assert.equal(capture('reference',html).url,'https://example.com/show');
});
test('school overrides only the due selector while inheriting title and description',()=>{
  const rules=[...catalog,{id:'second-school',extends:'assignment',host:'second.test',overrides:{date:'time#school-due'}}];
  const html='<html><body id="page-mod-assign-view"><main id="region-main"><h2>Lab 7</h2><p id="intro">Read chapter 7</p><time id="school-due" datetime="2027-04-01T18:00"></time></main></body></html>';
  const page=capture('todo',html,{rules,url:'https://second.test/mod/assign/view.php?id=7'});
  assert.equal(page.title,'Lab 7');assert.equal(page.text,'Read chapter 7');assert.equal(page.date,'2027-04-01T18:00');
});

test('selection on a course page and its assignment detail share an account-scoped identity',()=>{
  const url='https://second.test/course/view.php?id=2';
  const {document}=parseHTML('<html><body data-userid="81"><a href="https://second.test/mod/assign/view.php?id=44">Lab 11</a></body></html>');
  const templates=resolveTemplates(catalog,'todo','second.test');
  const selection={anchorNode:document.querySelector('a').firstChild,toString:()=>'Lab 11'};
  const row=runInNewContext('('+projectPage.toString()+')(templates,"todo")',{
    URL,location:new URL(url),document,templates,window:{getSelection:()=>selection}
  });
  const detail=capture('todo','<html><body id="page-mod-assign-view" data-userid="81"><main id="region-main"><h2>Lab 11</h2><p id="intro">Exercise</p></main></body></html>',{url:row.url});
  assert.equal(row.activity.detail,false);assert.equal(detail.activity.detail,true);
  assert.equal(row.activity.id,detail.activity.id);assert.equal(row.activity.principal,detail.activity.principal);
});
test('notice preserves publisher and publication date independently of display expiry',()=>{
  const page=capture('notice','<title>通知</title><p itemprop="articleBody">展出至年底</p><span itemprop="publisher">博物馆</span><time itemprop="datePublished" datetime="2027-01-01T09:00"></time><time itemprop="expires" datetime="2027-12-31"></time>');
  assert.equal(page.publisher,'博物馆');assert.equal(page.text,'展出至年底');assert.equal(page.date,'2027-01-01T09:00');
});
test('preview removes authorization parameters and URL fragments',()=>{
  const page=capture('reference','<title>资料</title>',{url:'https://example.com/doc?id=7&code=test#access_token=test'});
  assert.equal(page.url,'https://example.com/doc?id=7');
});

test('link-only saves preserve a plain client-side route',()=>{
  const url='https://example.test/#/exhibits/7';
  assert.equal(capture('reference','<title>展厅</title>',{url}).url,url);
});
