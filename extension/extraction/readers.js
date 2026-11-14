/** Browser port: only rendered DOM in the main frame, never debugger/CDP. */
export const SCOPED_FILES = ['content/scoped/dom.js', 'content/scoped/moodle-model.js', 'content/scoped/moodle-content.js', 'content/scoped/moodle-regions.js', 'content/scoped/moodle.js', 'content/scoped/student.js', 'content/scoped/people.js', 'content/scoped/generic.js', 'content/scoped/runtime.js'];

export class DomPageReader {
  constructor(browser, {timeout = 12000, pause = ms => new Promise(r => setTimeout(r, ms))} = {}) { this.browser = browser; this.timeout = timeout; this.pause = pause; }
  async invoke(tabId, method, input = null, timeout=this.timeout) {
    let timer;
    try { return await Promise.race([this.execute(tabId,method,input),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('render_timeout')),timeout);})]); }
    finally {clearTimeout(timer);}
  }
  async execute(tabId,method,input) {
    let answer;
    try {
      await this.browser.scripting.executeScript({target:{tabId,frameIds:[0]},injectImmediately:true,files:SCOPED_FILES});
      [answer] = await this.browser.scripting.executeScript({target:{tabId,frameIds:[0]},injectImmediately:true,func:(name,value)=>{
      try { return {ok:true,value:globalThis.CampusScoped[name](value)}; }
      catch(e) { return {ok:false,error:e.message}; }
      },args:[method,input]});
    } catch(e) {
      if(/gallery|web store|chrome:\/\//i.test(e.message))throw Error('restricted_page');
      if(/permission|cannot access|not allowed|host access/i.test(e.message))throw Error('permission_denied');
      throw Error('page_read_failed');
    }
    if(answer?.result?.ok!==true) throw Error(answer?.result?.error || 'page_read_failed');
    return answer.result.value;
  }
  metadata(tabId,timeout) { return this.invoke(tabId,'metadata',null,timeout); }
  async read(tabId, intent, choice) {
    const until=Date.now()+this.timeout,remaining=()=>Math.max(1,until-Date.now());
    const before=await this.metadata(tabId,remaining());
    let previous='', stable=0;
    while(Date.now()<until) {
      let value;
      try { value=await this.invoke(tabId,'execute',{intent,choice},remaining()); }
      catch(e) { if(e.message!=='page_not_ready') throw e; }
      assertSamePage(before,await this.metadata(tabId,remaining()));
      if(value) {
        const key=JSON.stringify([value.records,value.choices,value.navigation,value.coverage]);
        stable=key===previous?stable+1:0;
        if(stable>=2) return value;
        previous=key;
      }
      await this.pause(250);
    }
    throw Error('render_timeout');
  }
}

export function assertSamePage(before,after) {
  if(before.url!==after.url) throw Error('route_mismatch');
  if(after.login) throw Error('need_login');
  if(before.account?.native!==after.account?.native) throw Error('account_mismatch');
}
