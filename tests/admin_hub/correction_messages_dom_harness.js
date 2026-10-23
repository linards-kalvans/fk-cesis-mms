/* Minimal DOM harness for static/admin_hub/correction_messages.js.
 *
 * stdin:  {"tree": <DOM tree>, "actions": [...], "responses": [...],
 *          "supportDialog": true}
 * argv[2]: path to correction_messages.js
 * stdout: JSON snapshot after the actions.
 *
 * No npm dependency. It implements only the DOM/fetch surface the shipped
 * script uses, so the regression exercises real event handling instead of
 * matching source strings. This is not browser proof: CSS hover, native
 * dialog modality and Escape handling remain manual checks.
 */
"use strict";

const fs = require("fs");
const vm = require("vm");

const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"]);

function decode(value) {
  return String(value)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

class ClassList {
  constructor(element) {
    this.element = element;
  }
  tokens() {
    return (this.element.getAttribute("class") || "").split(/\s+/).filter(Boolean);
  }
  contains(token) {
    return this.tokens().includes(token);
  }
}

class Element {
  constructor(tag, attrs) {
    this.tagName = String(tag || "").toUpperCase();
    this.attrs = Object.assign({}, attrs || {});
    this.children = [];
    this.parentNode = null;
    this.listeners = Object.create(null);
    this.classList = new ClassList(this);
  }

  get open() {
    return this.hasAttribute("open");
  }
  set open(value) {
    if (value) this.setAttribute("open", "");
    else this.removeAttribute("open");
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }
  hasAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name);
  }
  removeAttribute(name) {
    delete this.attrs[name];
  }

  get textContent() {
    return this.children.map((child) => (child.text !== undefined ? child.text : child.textContent)).join("");
  }
  set textContent(value) {
    this.children = [{ text: String(value) }];
  }
  set innerHTML(value) {
    const fragment = parseFragment(String(value));
    this.children = fragment.children;
    this.children.forEach((child) => {
      child.parentNode = this;
    });
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  addEventListener(type, handler) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(handler);
  }
  dispatch(type, event) {
    (this.listeners[type] || []).forEach((handler) => handler(event));
  }

  focus() {
    activeElement = this;
  }

  descendants() {
    const out = [];
    const walk = (node) => {
      node.children.forEach((child) => {
        if (child instanceof Element) {
          out.push(child);
          walk(child);
        }
      });
    };
    walk(this);
    return out;
  }

  querySelectorAll(selector) {
    return this.descendants().filter((node) => matches(node, selector));
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
  closest(selector) {
    let node = this;
    while (node instanceof Element) {
      if (matches(node, selector)) return node;
      node = node.parentNode;
    }
    return null;
  }
}

class Root extends Element {
  constructor() {
    super("#root", {});
    this.documentListeners = Object.create(null);
  }
  addEventListener(type, handler) {
    if (!this.documentListeners[type]) this.documentListeners[type] = [];
    this.documentListeners[type].push(handler);
  }
  dispatchDocument(type, event) {
    (this.documentListeners[type] || []).forEach((handler) => handler(event));
  }
  createElement(tag) {
    return new Element(tag, {});
  }
}

let activeElement = null;

function matchesSimple(element, selector) {
  let rest = selector.trim();
  const tag = rest.match(/^[a-zA-Z][\w-]*/);
  if (tag) {
    if (element.tagName !== tag[0].toUpperCase()) return false;
    rest = rest.slice(tag[0].length);
  }
  while (rest.length) {
    if (rest[0] === ".") {
      const token = rest.match(/^\.([\w-]+)/);
      if (!token || !element.classList.contains(token[1])) return false;
      rest = rest.slice(token[0].length);
      continue;
    }
    if (rest[0] === "[") {
      const token = rest.match(/^\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'))?\]/);
      if (!token || !element.hasAttribute(token[1])) return false;
      const expected = token[2] !== undefined ? token[2] : token[3];
      if (expected !== undefined && element.getAttribute(token[1]) !== expected) return false;
      rest = rest.slice(token[0].length);
      continue;
    }
    return false;
  }
  return true;
}

function matches(element, selector) {
  return String(selector)
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .some((complex) => {
      const parts = complex.split(/\s+/).filter(Boolean);
      if (!parts.length || !matchesSimple(element, parts[parts.length - 1])) return false;
      let index = parts.length - 2;
      let node = element.parentNode;
      while (index >= 0) {
        if (!(node instanceof Element)) return false;
        if (matchesSimple(node, parts[index])) index -= 1;
        node = node.parentNode;
      }
      return true;
    });
}

function parseAttrs(raw) {
  const attrs = {};
  const re = /([\w-]+)(?:\s*=\s*"([^"]*)")?/g;
  let match;
  while ((match = re.exec(raw || ""))) {
    attrs[match[1]] = match[2] === undefined ? "" : decode(match[2]);
  }
  return attrs;
}

function appendText(parent, text) {
  if (text) parent.children.push({ text: decode(text) });
}

function parseFragment(html) {
  const container = new Element("#fragment", {});
  const stack = [container];
  const re = /<(\/)?([a-zA-Z][\w-]*)((?:\s+[^>]*?)?)(\/)?>/g;
  let last = 0;
  let match;
  while ((match = re.exec(html))) {
    appendText(stack[stack.length - 1], html.slice(last, match.index));
    const closing = Boolean(match[1]);
    const tag = match[2].toLowerCase();
    if (closing) {
      for (let index = stack.length - 1; index > 0; index -= 1) {
        if (stack[index].tagName === tag.toUpperCase()) {
          stack.length = index;
          break;
        }
      }
    } else {
      const element = new Element(tag, parseAttrs(match[3] || ""));
      stack[stack.length - 1].appendChild(element);
      if (!VOID.has(tag) && !match[4]) stack.push(element);
    }
    last = re.lastIndex;
  }
  appendText(stack[stack.length - 1], html.slice(last));
  return container;
}

function build(node) {
  if (node.text !== undefined) return { text: node.text };
  const element = new Element(node.tag, node.attrs);
  (node.children || []).forEach((child) => element.appendChild(build(child)));
  return element;
}

const root = new Root();
(payload.tree.children || []).forEach((node) => root.appendChild(build(node)));

const dialog = root.querySelector("[data-correction-dialog]");
if (dialog) {
  if (payload.supportDialog !== false) {
    dialog.showModal = function () {
      this.setAttribute("open", "");
    };
  }
  dialog.close = function () {
    this.removeAttribute("open");
    this.dispatch("close", { target: this });
  };
}

const fetchCalls = [];
let responseIndex = 0;
const responses = payload.responses || [];
const responseMode = payload.responseMode || "ok";

const sandbox = {
  console,
  document: root,
  window: {},
  setTimeout,
  clearTimeout,
  AbortController,
  fetch(url, options) {
    fetchCalls.push({ url: String(url), headers: (options && options.headers) || {} });
    const spec =
      responseMode === "error"
        ? { ok: false, status: 500, html: "" }
        : responses[Math.min(responseIndex, responses.length - 1)] || {
            ok: true,
            status: 200,
            html: "",
          };
    responseIndex += 1;
    return Promise.resolve({
      ok: spec.ok !== false,
      status: spec.status || 200,
      redirected: Boolean(spec.redirected),
      text() {
        return Promise.resolve(spec.html || "");
      },
    });
  },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), sandbox, {
  filename: "correction_messages.js",
});

function click(element) {
  const event = {
    target: element,
    defaultPrevented: false,
    preventDefault() {
      this.defaultPrevented = true;
    },
  };
  let node = element;
  while (node instanceof Element) {
    node.dispatch("click", event);
    node = node.parentNode;
  }
  root.dispatchDocument("click", event);
  return event;
}

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

function activeSummary() {
  if (!(activeElement instanceof Element)) return null;
  return { tag: activeElement.tagName, attrs: Object.assign({}, activeElement.attrs) };
}

(async function main() {
  const state = { lastClickDefaultPrevented: null, lastClickBody: null };
  for (const action of payload.actions || []) {
    if (action.type === "click") {
      const target = root.querySelector(action.selector);
      if (!target) throw new Error(`no element for ${action.selector}`);
      const event = click(target);
      state.lastClickDefaultPrevented = event.defaultPrevented;
      state.lastClickBody = body() ? body().textContent : null;
    } else if (action.type === "focus") {
      const target = root.querySelector(action.selector);
      if (!target) throw new Error(`no element for ${action.selector}`);
      target.focus();
    } else if (action.type === "hover") {
      const target = root.querySelector(action.selector);
      if (!target) throw new Error(`no element for ${action.selector}`);
      target.dispatch("mouseenter", { target });
    } else if (action.type === "flush") {
      await flush();
    } else {
      throw new Error(`unknown action ${action.type}`);
    }
  }

  function body() {
    return root.querySelector("[data-correction-body]");
  }
  function fallback() {
    return root.querySelector("[data-correction-fallback]");
  }

  process.stdout.write(
    JSON.stringify({
      fetchCalls,
      fetchCount: fetchCalls.length,
      loadingText: state.lastClickBody,
      bodyText: body() ? body().textContent : "",
      bodyBusy: body() ? body().getAttribute("aria-busy") : null,
      dialogOpen: dialog ? dialog.open : false,
      fallbackHref: fallback() ? fallback().getAttribute("href") : null,
      defaultPrevented: state.lastClickDefaultPrevented,
      activeElement: activeSummary(),
    })
  );
})().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
