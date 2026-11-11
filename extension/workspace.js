import {ExtensionClient} from './ui/client.js';
import {CaptureFormStore} from './ui/form-store.js';
import {CaptureView,errorText} from './ui/view.js';
import {CaptureController} from './ui/controller.js';
const view=new CaptureView(document);
const controller=new CaptureController({browser:chrome,client:new ExtensionClient(chrome),forms:new CaptureFormStore(chrome.storage.local),view,location});
controller.init().catch(e=>view.status(errorText(e.message),true));
window.addEventListener('pagehide',()=>controller.dispose());
