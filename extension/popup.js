import {ExtensionClient} from './ui/client.js';
import {CaptureFormStore} from './ui/form-store.js';
import {CaptureView,errorText} from './ui/view.js';
import {CaptureController} from './ui/controller.js';
// Chrome measures a popup before modules finish loading. Keep its preferred
// window width independent of that initial viewport; inner content can scroll.
document.documentElement.classList.add('extension-popup');
const view=new CaptureView(document);
const controller=new CaptureController({browser:chrome,client:new ExtensionClient(chrome),forms:new CaptureFormStore(chrome.storage.local),view,location});
controller.init().catch(e=>view.status(errorText(e.message),true));
window.addEventListener('pagehide',()=>controller.dispose());
