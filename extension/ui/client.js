export class ExtensionClient {
  constructor(browser) { this.browser=browser; }
  async send(message) {
    let timer;
    try {
      const result=await Promise.race([this.browser.runtime.sendMessage(message),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('worker_timeout')),20000);})]);
      if(result?.ok!==true) throw Error(result?.error || 'worker_unavailable');
      return result.value;
    } finally {clearTimeout(timer);}
  }
}
