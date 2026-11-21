import {safeUrl} from '../extraction/sites.js';

/** Small DOM port shared by renderers; all page text remains text, never markup. */
export class DomView {
  constructor(document) { this.document = document; }
  $(id) { return this.document.getElementById(id); }
  node(tag, text = '', className = '') {
    const node = this.document.createElement(tag);
    node.textContent = text;
    node.className = className;
    return node;
  }
  button(text, action, className = '') {
    const button = this.node('button', text, className);
    button.type = 'button'; button.onclick = action;
    return button;
  }
  link(text, url) {
    const safe = safeUrl(url);
    if (!safe) return this.node('span', text);
    const link = this.node('a', text);
    link.href = safe; link.target = '_blank'; link.rel = 'noopener noreferrer';
    return link;
  }
  select(id, value) {
    const options = [...this.$(id).querySelectorAll('option')];
    for (const option of options) option.selected = false;
    const selected = options.find(option => option.value === value);
    if (selected) selected.selected = true;
  }
}
