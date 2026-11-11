// Isolated world only. DOM references never leave this invocation.
(() => {
  const R = globalThis.CampusScoped = {};
  R.adapters = [];
  R.normalize = value => {
    const a = '網絡編課業資訊獎學電郵辦師個這門當頁標題關鍵詞獲發佈電話職稱部張陳劉楊軟體計劃與時週後間';
    const b = '网络编课业资讯奖学电邮办师个这门当页标题关键词获发布电话职称部张陈刘杨软体计划与时周后间';
    return String(value || '').normalize('NFKC').toLowerCase().replace(/\s+/g, ' ').trim().split('').map(c => { const i = [...a].indexOf(c); return i < 0 ? c : [...b][i]; }).join('');
  };
  class DomAccess {
    excluded = 'nav,header,footer,aside,form,iframe,script,style,noscript,[hidden],[aria-hidden="true"],[role="navigation"],[role="contentinfo"]';
    constructor() { this.contentReads = []; }
    visible(node, navigation = false) {
      if (!node || node.closest(navigation ? '[hidden],[aria-hidden="true"],footer' : this.excluded)) return false;
      for (let p = node; p && globalThis.getComputedStyle; p = p.parentElement) {
        const s = getComputedStyle(p); if (s.display === 'none' || ['hidden','collapse'].includes(s.visibility)) return false;
      }
      return true;
    }
    label(node, navigation = false) { return this.visible(node, navigation) ? String(node.textContent || node.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim() : ''; }
    text(node, depth = 0) {
      if (!node || depth > 100) return '';
      if (node.nodeType === 3) return node.textContent;
      if (node.nodeType !== 1 || !this.visible(node) || node.matches('input,textarea,select,button,[contenteditable="true"]')) return '';
      return [...node.childNodes].map(n => this.text(n, depth + 1)).join('') + (/^(p|div|h[1-6]|li|dt|dd|tr|br|article|section|main)$/.test(node.localName) ? '\n' : '');
    }
    content(node) {
      if (!node) throw Error('selection_missing');
      this.contentReads.push(this.locator(node));
      const text = this.text(node).split('\n').map(s => s.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n');
      if (!text) throw Error('page_not_ready');
      if (text.length > 20000) throw Error('content_too_large');
      return text;
    }
    locator(node) {
      if (node.id) return `[id=${JSON.stringify(node.id)}]`;
      for (const key of ['data-assignment-id','data-notice-id','data-person-id','data-schedule-id']) if (node.hasAttribute(key)) return `[${key}=${JSON.stringify(node.getAttribute(key))}]`;
      const parts = [];
      for (let n = node; n && n !== document.body && parts.length < 12; n = n.parentElement) parts.unshift(`${n.localName}:nth-child(${[...n.parentElement?.children || []].indexOf(n) + 1})`);
      return 'body > ' + parts.join(' > ');
    }
    evidence(node, text) { return { channel: 'dom', locator: this.locator(node), text }; }
    match(text, query) { return !query || R.normalize(text).includes(R.normalize(query)); }
    url(link) {
      try { const u = new URL(link.getAttribute('href'), location.href); return ['http:','https:'].includes(u.protocol) && !u.username && !u.password && ![...u.searchParams.keys()].some(k=>/token|ticket|session|password|secret/i.test(k)) ? u : null; } catch { return null; }
    }
    metadata() {
      const local = ['localhost','127.0.0.1'].includes(location.hostname);
      const fixture = local ? document.querySelector('meta[name="campus-radar-fixture"]')?.content || '' : '';
      const source = fixture || ({'moodle.must.edu.mo':'moodle','student-wmweb.must.edu.mo':'student','infoportal-web.must.edu.mo':'student','classtimetable-coes-wmweb.must.edu.mo':'student','fie.must.edu.mo':'fie'})[location.hostname];
      const accountNode = document.querySelector('body[data-account-id],body[data-userid],.usermenu[data-userid],.usermenu [data-userid]');
      const account = accountNode?.getAttribute('data-account-id') || accountNode?.getAttribute('data-userid') || (() => { const a = document.querySelector('.usermenu a[href*="/user/profile.php"]'); return a ? new URL(a.getAttribute('href'),location.href).searchParams.get('id') || '' : ''; })();
      const login = /\/(login|sso|auth)(\/|\.|$)/i.test(location.pathname) || [...document.querySelectorAll('input[type="password"]')].some(n=>this.visible(n,true));
      return {url:location.href,title:document.title,source,fixture,account:{state:source==='fie'?'public':account?'known':'unknown',native:source==='fie'?'public':account},login,frames:document.querySelectorAll('iframe').length,ready:document.readyState};
    }
    labels(root, mapping) {
      const out = {};
      for (const [key, pattern] of Object.entries(mapping)) {
        const direct = root.querySelector(`[data-field="${key}"]`);
        if (direct && this.visible(direct)) { out[key] = this.label(direct); continue; }
        for (const label of root.querySelectorAll('dt,th')) if (this.visible(label) && pattern.test(R.normalize(label.textContent))) { const value = this.label(label.nextElementSibling); if (value) out[key] = value; }
      }
      return out;
    }
    record(entity_id, title, text, node, extras = {}) {
      if (!title || title.length > 300 || !text || text.length > 20000) throw Error('content_too_large');
      return {entity_id,title,text,url:location.href,fields:{},complete:true,evidence:this.evidence(node,text),...extras};
    }
  }
  R.DomAccess = DomAccess;
})();
