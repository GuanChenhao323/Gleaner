(() => {
  if(globalThis.CampusResidentGuard)return;
  const visible=n=>!n.closest('[hidden],[aria-hidden="true"]') && getComputedStyle(n).display!=='none' && getComputedStyle(n).visibility!=='hidden';
  const document_id=crypto.randomUUID();
  let dirty=false;
  document.addEventListener('input',e=>{if(e.target?.matches('input,textarea,[contenteditable="true"]'))dirty=true;},true);
  document.addEventListener('submit',()=>{dirty=true;},true);
  const inspect=()=>{
    const focused=document.hasFocus() && document.activeElement?.matches('input,textarea,[contenteditable="true"]');
    const unsaved=[...document.querySelectorAll('textarea,input:not([type="password"]):not([type="search"]):not([type="hidden"])')].some(n=>visible(n) && n.closest('form') && n.value!==n.defaultValue && !['checkbox','radio','button','submit'].includes(n.type));
    const editor=[...document.querySelectorAll('[contenteditable="true"]')].some(n=>visible(n) && n.textContent.trim().length>0);
    const controls=[...document.querySelectorAll('select,input[type="search"]')].filter(visible).slice(0,30).map((n,i)=>[n.id || n.name || n.getAttribute('aria-label') || n.localName+':'+i, n.localName==='select'?[...n.selectedOptions].map(o=>o.value):n.value]);
    return {document_id,busy:Boolean(dirty || focused || unsaved || editor),view:JSON.stringify(controls)};
  };
  globalThis.CampusResidentGuard={inspect};
})();
