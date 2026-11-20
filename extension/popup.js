import {initializeLanguage, retranslate} from './ui/i18n.js';
import {ExtensionClient} from './ui/client.js';
import {CaptureFormStore} from './ui/form-store.js';
import {CaptureView,errorText} from './ui/view.js';
import {CaptureController} from './ui/controller.js';
// Chrome measures a popup before modules finish loading. Keep its preferred
// window width independent of that initial viewport; inner content can scroll.
document.documentElement.classList.add('extension-popup');
await initializeLanguage(document, chrome.storage.local, chrome.i18n?.getUILanguage?.() || navigator.language);
const view=new CaptureView(document);
const controller=new CaptureController({browser:chrome,client:new ExtensionClient(chrome),forms:new CaptureFormStore(chrome.storage.local),view,location});
controller.init().catch(e=>view.status(errorText(e.message),true));
window.addEventListener('pagehide',()=>controller.dispose());

import {bindIntentPanel} from './ui/intent-panel.js';
bindIntentPanel(document,chrome,new ExtensionClient(chrome));

import {bindPageControl} from './ui/page-control.js';
bindPageControl(document,chrome,new ExtensionClient(chrome));

// Re-render copy in place: keep input, selection, requests and captured source data.
document.addEventListener('languagechange', () => {
  for (const id of ['status', 'connection-status', 'connection-error', 'account', 'login',
    'save-hint', 'intent-status', 'intent-date-label', 'intent-original-date', 'protocol-message']) {
    const node = document.getElementById(id);
    if (id === 'account' && controller.cfg.email) continue;
    node.textContent = retranslate(node.textContent);
  }
  view.preview.key = null;
  view.receipts.key = null;
  if (!controller.task) view.preview.clear();
  view.source.render();
  if (controller.currentTab) controller.showPage(controller.historical
    ? {url: controller.form.url, title: controller.task?.result?.title || controller.form.query}
    : controller.currentTab);
  controller.render();
  if (!document.getElementById('history-panel').hidden) void controller.guard(() => controller.history())();
});
