import english from './locales/en.js';

let language = 'zh-CN';
const rendered = new Map();
export const getLanguage = () => language;
export function setLanguage(value) { language = value === 'en' ? 'en' : 'zh-CN'; }

/** Translate application copy only. Interpolated page content is never translated. */
export function t(message, ...values) {
  const key = Array.isArray(message)
    ? message.map((part, i) => part + (i < values.length ? `{${i}}` : '')).join('') : message;
  const template = language === 'en' ? english[key] ?? key : key;
  const result = values.length ? template.replace(/\{(\d+)\}/g, (match, index) => index < values.length ? String(values[index]) : match) : template;
  // Used only for transient status fields when changing language without reloading.
  rendered.set(result, {key, values});
  return result;
}
export function retranslate(message) {
  const source = rendered.get(message);
  if (!source) return message;
  const template = language === 'en' ? english[source.key] ?? source.key : source.key;
  const result = template.replace(/\{(\d+)\}/g, (match, index) => index < source.values.length ? String(source.values[index]) : match);
  rendered.set(result, source);
  return result;
}

/** Capture static HTML copy once, before renderers insert source titles or text. */
export function staticLocalizer(document) {
  const bindings = [];
  function visit(node) {
    if (node.nodeType === 3 && /\p{Script=Han}/u.test(node.textContent)) {
      const original = node.textContent, key = original.trim();
      bindings.push({read: () => node.textContent, write: value => {node.textContent = value;}, key,
        prefix: original.slice(0, original.indexOf(key)), suffix: original.slice(original.indexOf(key) + key.length), last: original});
    }
    if (node.nodeType === 1) for (const attr of ['title', 'aria-label', 'placeholder']) {
      const key = node.getAttribute(attr);
      if (key && /\p{Script=Han}/u.test(key)) bindings.push({read: () => node.getAttribute(attr), write: value => node.setAttribute(attr, value), key, prefix: '', suffix: '', last: key});
    }
    for (const child of node.childNodes || []) visit(child);
  }
  visit(document);
  return () => {
    document.documentElement.lang = language;
    for (const binding of bindings) {
      // A renderer may own this node now. Never overwrite its data or state.
      if (binding.read() !== binding.last) continue;
      binding.last = binding.prefix + t(binding.key) + binding.suffix;
      binding.write(binding.last);
    }
  };
}

export async function initializeLanguage(document, storage, browserLanguage = 'zh-CN') {
  const localize = staticLocalizer(document);
  let saved;
  try { saved = (await storage.get('ui_language')).ui_language; } catch { /* UI remains usable without storage. */ }
  setLanguage(saved || (browserLanguage.toLowerCase().startsWith('en') ? 'en' : 'zh-CN'));
  localize();
  const select = document.getElementById('language');
  select.value = language;
  select.addEventListener('change', async () => {
    const previous = language, selected = select.value;
    select.disabled = true;
    try {
      await storage.set({ui_language: selected});
      setLanguage(selected);
      localize();
      document.dispatchEvent(new document.defaultView.Event('languagechange'));
    } catch {
      setLanguage(previous); select.value = previous;
    } finally { select.disabled = false; }
  });
}
