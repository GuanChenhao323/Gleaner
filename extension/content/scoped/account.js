(() => {
  const R=globalThis.CampusScoped;
  /** Account identity is read separately from content eligibility, never from mail rows. */
  class AccountControlProbe {
    read() {
      const visible=new R.RenderedVisibility(), emails=new Set();
      const add=value=>{
        const matches=String(value || '').normalize('NFKC').match(/[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+/gi) || [];
        for(const email of matches)emails.add(email.toLowerCase());
      };
      for(const node of document.querySelectorAll('header [data-account-email],[role="banner"] [data-account-email],header [data-current-account],[role="banner"] [data-current-account]')) {
        if(visible.allows(node))add(node.getAttribute('data-account-email') || node.getAttribute('data-current-account'));
      }
      for(const node of document.querySelectorAll('button[aria-label],a[aria-label],[role="button"][aria-label]')) {
        const label=node.getAttribute('aria-label') || '';
        if(label.length<=400 && /(?:google\s*account|current\s*account|signed\s*in\s*as|当前账号|目前帳戶|目前帳號|google\s*帳戶|google\s*帐号|google\s*账号|google\s*账户)/i.test(label) && visible.allows(node))add(label);
      }
      return emails.size===1?{state:'known',native:[...emails][0],probe:'account-control-email-v1'}:{state:'unknown',native:''};
    }
  }
  R.AccountControlProbe=AccountControlProbe;
})();
