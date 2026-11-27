/* Minimal DOM/fetch harness for static/js/agreement_preview.js — test support.
 *
 * stdin:  {"tree": <DOM tree>, "actions": [...]}
 * argv[2]: path to agreement_preview.js
 * stdout: JSON snapshot after the actions.
 *
 * No npm dependency. It implements only the DOM/fetch surface the shipped
 * script uses plus the signing-path switch expected by the Slice A local
 * preview. Deferred fetch responses let the test resolve an older request
 * after a newer one, proving stale responses are ignored.
 */
"use strict";

const fs = require("fs");
const vm = require("vm");

const payload = JSON.parse(fs.readFileSync(0, "utf8"));

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
  add(token) {
    const tokens = this.tokens();
    if (!tokens.includes(token)) {
      tokens.push(token);
      this.element.setAttribute("class", tokens.join(" "));
    }
  }
  remove(token) {
    this.element.setAttribute(
      "class",
      this.tokens().filter((item) => item !== token).join(" ")
    );
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
    this.style = {};
    this._scrollTop = 0;
    // Minimal HTMLImageElement load-state surface: setting a new src starts a
    // fresh load, so a delayed event from the previous resource is observable.
    this.complete = false;
    this.naturalWidth = 0;
  }

  get hidden() {
    return this.hasAttribute("hidden");
  }
  set hidden(value) {
    if (value) this.setAttribute("hidden", "");
    else this.removeAttribute("hidden");
  }

  get disabled() {
    return this.hasAttribute("disabled");
  }
  set disabled(value) {
    if (value) this.setAttribute("disabled", "");
    else this.removeAttribute("disabled");
  }

  get src() {
    return this.getAttribute("src");
  }
  set src(value) {
    if (this.getAttribute("src") !== String(value)) {
      this.complete = false;
      this.naturalWidth = 0;
    }
    this.setAttribute("src", value);
  }

  get alt() {
    return this.getAttribute("alt");
  }
  set alt(value) {
    this.setAttribute("alt", value);
  }

  get value() {
    return this.getAttribute("value") || "";
  }
  set value(value) {
    this.setAttribute("value", String(value));
  }

  get scrollTop() {
    return this._scrollTop;
  }
  set scrollTop(value) {
    this._scrollTop = value;
  }

  get dataset() {
    const self = this;
    return new Proxy(
      {},
      {
        get(_target, property) {
          const name =
            "data-" +
            String(property).replace(/[A-Z]/g, (char) => "-" + char.toLowerCase());
          return self.getAttribute(name) === null
            ? undefined
            : self.getAttribute(name);
        },
      }
    );
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name)
      ? this.attrs[name]
      : null;
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
    return this.children
      .map((child) => (child.text !== undefined ? child.text : child.textContent))
      .join("");
  }
  set textContent(value) {
    this.children = [{ text: String(value) }];
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
    const detail = event || { target: this, preventDefault() {} };
    (this.listeners[type] || []).forEach((handler) => handler(detail));
  }

  focus() {
    globalThis.activeElement = this;
  }

  showModal() {
    this.setAttribute("open", "");
  }

  close() {
    this.removeAttribute("open");
  }

  getBoundingClientRect() {
    return { left: 0, top: 0, right: 800, bottom: 600 };
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
}

class Root extends Element {
  constructor() {
    super("#root", {});
    this.documentListeners = Object.create(null);
    this.hidden = false;
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
  getElementById(id) {
    return this.descendants().find((node) => node.getAttribute("id") === id) || null;
  }
}

function build(node) {
  if (node.text !== undefined) return { text: node.text };
  const element = new Element(node.tag, node.attrs);
  (node.children || []).forEach((child) => element.appendChild(build(child)));
  return element;
}

function splitSelector(selector) {
  const parts = [];
  let current = "";
  let quote = null;
  for (const char of selector) {
    if (quote) {
      current += char;
      if (char === quote) quote = null;
    } else if (char === '"' || char === "'") {
      quote = char;
      current += char;
    } else if (char === ",") {
      parts.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  parts.push(current);
  return parts.map((part) => part.trim()).filter(Boolean);
}

function matchesSimple(element, selector) {
  let rest = selector.trim();
  const tag = rest.match(/^[a-zA-Z][\w-]*/);
  if (tag) {
    if (element.tagName !== tag[0].toUpperCase()) return false;
    rest = rest.slice(tag[0].length);
  }

  while (rest.length) {
    if (rest[0] === "#") {
      const token = rest.match(/^#([\w-]+)/);
      if (!token || element.getAttribute("id") !== token[1]) return false;
      rest = rest.slice(token[0].length);
      continue;
    }
    if (rest[0] === ".") {
      const token = rest.match(/^\.([\w-]+)/);
      if (!token || !element.classList.contains(token[1])) return false;
      rest = rest.slice(token[0].length);
      continue;
    }
    if (rest[0] === "[") {
      const token = rest.match(/^\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]/);
      if (!token) return false;
      if (!element.hasAttribute(token[1])) return false;
      const expected =
        token[2] !== undefined
          ? token[2]
          : token[3] !== undefined
            ? token[3]
            : token[4];
      if (expected !== undefined && element.getAttribute(token[1]) !== expected) {
        return false;
      }
      rest = rest.slice(token[0].length);
      continue;
    }
    if (rest.startsWith(":not(")) {
      const close = rest.indexOf(")");
      if (close === -1) return false;
      if (matchesSimple(element, rest.slice(":not(".length, close))) return false;
      rest = rest.slice(close + 1);
      continue;
    }
    return false;
  }
  return true;
}

function matches(element, selector) {
  return splitSelector(selector).some((complex) => {
    const parts = complex.split(/\s+/).filter(Boolean);
    if (!parts.length || !matchesSimple(element, parts[parts.length - 1])) {
      return false;
    }
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

const root = new Root();
(payload.tree.children || []).forEach((node) => root.appendChild(build(node)));

const pendingFetch = [];
const unresolved = [];
const observers = [];

function fakeFetch(url) {
  return new Promise((resolve, reject) => {
    pendingFetch.push({ url: String(url), resolve, reject });
  });
}

class IntersectionObserver {
  constructor(callback) {
    this.callback = callback;
    this.elements = [];
    this.disconnected = false;
    observers.push(this);
  }
  observe(element) {
    this.elements.push(element);
  }
  disconnect() {
    this.disconnected = true;
  }
}

function triggerIntersection() {
  observers.forEach((observer) => {
    if (observer.disconnected) return;
    observer.callback(
      observer.elements.map((element) => ({ isIntersecting: true, target: element })),
      observer
    );
  });
}

const documentListeners = Object.create(null);
const windowListeners = Object.create(null);
const fakeWindow = {
  location: { href: "http://testserver/register/" },
  setTimeout,
  clearTimeout,
  addEventListener(type, handler) {
    if (!windowListeners[type]) windowListeners[type] = [];
    windowListeners[type].push(handler);
  },
  getComputedStyle() {
    return {
      paddingLeft: "0px",
      paddingRight: "0px",
      paddingTop: "0px",
      paddingBottom: "0px",
    };
  },
};

const document = root;
document.addEventListener = (type, handler) => {
  if (!documentListeners[type]) documentListeners[type] = [];
  documentListeners[type].push(handler);
};
document.dispatchDocument = (type, event) => {
  (documentListeners[type] || []).forEach((handler) => handler(event));
};
document.hidden = false;

const sandbox = {
  console,
  document,
  window: fakeWindow,
  location: fakeWindow.location,
  getComputedStyle: fakeWindow.getComputedStyle,
  setTimeout,
  clearTimeout,
  fetch: fakeFetch,
  IntersectionObserver,
  URL,
  URLSearchParams,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), sandbox, {
  filename: "agreement_preview.js",
});

async function settle() {
  for (let index = 0; index < 5; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

function responseFor(action) {
  return {
    ok: action.ok !== false,
    status: action.status || 200,
    redirected: false,
    json: async () => action.manifest,
  };
}

async function apply(action) {
  if (action.type === "intersect") {
    triggerIntersection();
    await settle();
    return;
  }
  if (action.type === "settle") {
    await settle();
    return;
  }
  if (action.type === "resolve") {
    const tracker = pendingFetch[action.index];
    if (!tracker) {
      unresolved.push(action.index);
      return;
    }
    tracker.resolve(responseFor(action));
    await settle();
    return;
  }
  if (action.type === "change-path") {
    const field = action.selector
      ? root.querySelector(action.selector)
      : root.getElementById(action.id);
    if (!field) throw new Error(`no signing-path field ${action.selector || action.id}`);
    field.value = action.value;
    field.dispatch("change", { target: field, preventDefault() {} });
    await settle();
    return;
  }
  if (action.type === "image-event") {
    const image = root.querySelector("[data-preview-image]");
    if (!image) throw new Error("no preview image");
    if (action.complete !== undefined) image.complete = Boolean(action.complete);
    if (action.naturalWidth !== undefined) {
      image.naturalWidth = Number(action.naturalWidth);
    }
    image.dispatch(action.event, { target: image, preventDefault() {} });
    await settle();
    return;
  }
  if (action.type === "visibilitychange") {
    document.hidden = Boolean(action.hidden);
    document.dispatchDocument("visibilitychange", { target: document });
    await settle();
    return;
  }
  throw new Error(`unknown action ${action.type}`);
}

(async () => {
  for (const action of payload.actions || []) {
    await apply(action);
  }

  const image = root.querySelector("[data-preview-image]");
  const status = root.querySelector("[data-preview-status]");
  const paper = root.querySelector("[data-preview-paper]");
  const pageLabel = root.querySelector("[data-preview-page]");
  const retry = root.querySelector("[data-preview-retry]");
  const pathField = root.getElementById("id_preferred_agreement_signing");

  process.stdout.write(
    JSON.stringify({
      fetchCount: pendingFetch.length,
      fetchCalls: pendingFetch.map((item) => item.url),
      unresolved,
      imageSrc: image ? image.getAttribute("src") : null,
      imageAlt: image ? image.getAttribute("alt") : null,
      imageComplete: image ? image.complete : null,
      imageNaturalWidth: image ? image.naturalWidth : null,
      statusText: status ? status.textContent : null,
      statusHidden: status ? status.hidden : null,
      paperHidden: paper ? paper.hidden : null,
      retryHidden: retry ? retry.hidden : null,
      pageLabel: pageLabel ? pageLabel.textContent : null,
      pathValue: pathField ? pathField.value : null,
    })
  );
})();
