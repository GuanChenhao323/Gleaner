// Sanitized structures only; never requests a production school host.
import fs from 'node:fs';
import vm from 'node:vm';
import {parseHTML} from 'linkedom';
import {SCOPED_FILES} from '../extraction/readers.js';
import {IntentParser} from '../extraction/intent.js';
export const parser=new IntentParser();
export function rendered(html,url='https://moodle.must.edu.mo/my/') {
  const {document}=parseHTML(/^<!doctype/i.test(html)?html:`<!doctype html><html><head><title>合成页面</title></head><body>${html}</body></html>`);
  Object.defineProperty(document,'readyState',{value:'complete',configurable:true});
  const context=vm.createContext({document,location:new URL(url),URL,Date});
  for(const file of SCOPED_FILES) vm.runInContext(fs.readFileSync(new URL('../'+file,import.meta.url),'utf8'),context);
  return {document,context,read:(query,choice)=>JSON.parse(JSON.stringify(context.CampusScoped.execute({intent:parser.parse(query),choice})))};
}
export function courses({ambiguous=false,inline=true}={}) {
  return '<main id="region-main">'+[[101,'網絡編程',[1101,1102]],[202,'数据科学',[2201]],...(ambiguous?[[404,'网络编程（重修班）',[4401]]]:[])].map(([id,name,ids])=>`<section data-course-id="${id}" data-semester="2026秋"><a href="/course/view.php?id=${id}">${name}</a>${ids.map(aid=>`<li class="activity" data-assignment-id="${aid}"><a href="/mod/assign/view.php?id=${aid}">${name} 实验 ${aid}</a>${inline?`<div class="activity-description">${name} 原始要求 ${aid}</div>`:''}</li>`).join('')}</section>`).join('')+'</main>';
}
export const storage=()=>{const data={};return {data,get:async key=>({[key]:structuredClone(data[key])}),set:async p=>Object.assign(data,structuredClone(p))};};
