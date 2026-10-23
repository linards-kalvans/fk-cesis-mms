/* Minimal DOM harness for static/admin_hub/viewer.js — test support only.
 *
 * stdin:  {"tree": <viewer DOM tree from tests/admin_hub/viewer_markup.py>,
 *          "actions": [ ... ]}
 * argv[2]: path to viewer.js
 * stdout: JSON snapshot of the viewer state after the actions.
 *
 * No npm dependency: this implements only the DOM surface viewer.js uses
 * (query selectors, classList, hidden/disabled reflection, listeners, image
 * load/error, keyboard events), so the regression exercises real JS behavior
 * instead of matching source strings.
 */
"use strict";

const fs = require("fs");
const vm = require("vm");

const payload = JSON.parse(fs.readFileSync(0, "utf8"));

class ClassList {
  constructor(element) {
    this.element = element;
  }
  _tokens() {
    const value = this.element.getAttribute("class") || "";
    return value.split(/\s+/).filter(Boolean);
  }
  _write(tokens) {
    this.element.setAttribute("class", tokens.join(" "));
  }
  add(token) {
    const tokens = this._tokens();
    if (!tokens.includes(token)) {
      tokens.push(token);
      this._write(tokens);
    }
  }
  remove(token) {
    this._write(this._tokens().filter((item) => item !== token));
  }
  contains(token) {
    return this._tokens().includes(token);
  }
  toggle(token) {
    if (this.contains(token)) {
      this.remove(token);
      return false;
    }
    this.add(token);
    return true;
  }
}

class Element {
  constructor(tag, attrs) {
    this.tagName = String(tag || "").toUpperCase();
    this.attrs = Object.assign({}, attrs || {});
    this.children = [];
    this.parentNode = null;
    this.listeners = Object.create(null);
    this.style = {};
    this.classList = new ClassList(this);
    this.complete = false;
    this.naturalWidth = 0;
    this.naturalHeight = 0;
    this.clientWidth = 600;
    this.clientHeight = 400;
  }

  get hidden() {
    return this.hasAttribute("hidden");
  }
  set hidden(value) {
    if (value) {
      this.setAttribute("hidden", "");
    } else {
      this.removeAttribute("hidden");
    }
  }

  get disabled() {
    return this.hasAttribute("disabled");
  }
  set disabled(value) {
    if (value) {
      this.setAttribute("disabled", "");
    } else {
      this.removeAttribute("disabled");
    }
  }

  get href() {
    return this.getAttribute("href");
  }
  set href(value) {
    this.setAttribute("href", value);
  }

  get src() {
    return this.getAttribute("src");
  }
  set src(value) {
    this.setAttribute("src", value);
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

  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name)
      ? this.attrs[name]
      : null;
  }
  hasAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name);
  }
  removeAttribute(name) {
    delete this.attrs[name];
  }

  addEventListener(type, handler) {
    if (!this.listeners[type]) {
      this.listeners[type] = [];
    }
    this.listeners[type].push(handler);
  }

  dispatch(type, event) {
    const detail = event || { target: this, preventDefault() {} };
    (this.listeners[type] || []).forEach((handler) => handler(detail));
  }

  click() {
    this.dispatch("click", {
      target: this,
      preventDefault() {},
    });
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
  }
  addEventListener(type, handler) {
    if (!this.documentListeners[type]) {
      this.documentListeners[type] = [];
    }
    this.documentListeners[type].push(handler);
  }
  dispatchDocument(type, event) {
    (this.documentListeners[type] || []).forEach((handler) => handler(event));
  }
  createElement(tag) {
    return new Element(tag, {});
  }
}

function build(node) {
  if (node.text !== undefined) {
    return { text: node.text };
  }
  const element = new Element(node.tag, node.attrs);
  (node.children || []).forEach((child) => {
    element.appendChild(build(child));
  });
  return element;
}

function splitSelector(selector) {
  const parts = [];
  let current = "";
  let quote = null;
  for (const char of selector) {
    if (quote) {
      current += char;
      if (char === quote) {
        quote = null;
      }
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
    if (element.tagName !== tag[0].toUpperCase()) {
      return false;
    }
    rest = rest.slice(tag[0].length);
  }

  while (rest.length) {
    if (rest[0] === ".") {
      const token = rest.match(/^\.([\w-]+)/);
      if (!token || !element.classList.contains(token[1])) {
        return false;
      }
      rest = rest.slice(token[0].length);
      continue;
    }
    if (rest[0] === "[") {
      const token = rest.match(/^\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'))?\]/);
      if (!token) {
        return false;
      }
      if (!element.hasAttribute(token[1])) {
        return false;
      }
      const expected = token[2] !== undefined ? token[2] : token[3];
      if (expected !== undefined && element.getAttribute(token[1]) !== expected) {
        return false;
      }
      rest = rest.slice(token[0].length);
      continue;
    }
    if (rest.startsWith(":not(")) {
      const close = rest.indexOf(")");
      if (close === -1) {
        return false;
      }
      const inner = rest.slice(":not(".length, close);
      if (matchesSimple(element, inner)) {
        return false;
      }
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
      if (!(node instanceof Element)) {
        return false;
      }
      if (matchesSimple(node, parts[index])) {
        index -= 1;
      }
      node = node.parentNode;
    }
    return true;
  });
}

const root = new Root();
(payload.tree.children || []).forEach((node) => root.appendChild(build(node)));

const windowListeners = Object.create(null);
const fakeWindow = {
  getComputedStyle() {
    return {
      paddingLeft: "0px",
      paddingRight: "0px",
      paddingTop: "0px",
      paddingBottom: "0px",
    };
  },
  addEventListener(type, handler) {
    if (!windowListeners[type]) {
      windowListeners[type] = [];
    }
    windowListeners[type].push(handler);
  },
};

const sandbox = {
  console,
  document: root,
  window: fakeWindow,
  getComputedStyle: fakeWindow.getComputedStyle,
  setTimeout,
  clearTimeout,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), sandbox, {
  filename: "viewer.js",
});

function stage(index) {
  return root.querySelector(`[data-viewer-stage="${index}"]`);
}

(payload.actions || []).forEach((action) => {
  if (action.type === "load" || action.type === "error") {
    const target = stage(action.stage);
    if (!target) {
      throw new Error(`no stage ${action.stage}`);
    }
    const image = target.querySelector("[data-viewer-doc]");
    if (!image) {
      throw new Error(`stage ${action.stage} has no [data-viewer-doc]`);
    }
    if (action.type === "load") {
      image.complete = true;
      image.naturalWidth = action.width || 800;
      image.naturalHeight = action.height || 600;
    }
    image.dispatch(action.type === "load" ? "load" : "error", {
      target: image,
      preventDefault() {},
    });
  } else if (action.type === "click-tab") {
    const tab = root.querySelector(`[data-viewer-tab="${action.tab}"]`);
    if (!tab) {
      throw new Error(`no tab ${action.tab}`);
    }
    tab.click();
  } else if (action.type === "click-control") {
    const control = root.querySelector(action.selector);
    if (!control) {
      throw new Error(`no control ${action.selector}`);
    }
    if (control.disabled) {
      throw new Error(`control ${action.selector} is disabled`);
    }
    control.click();
  } else if (action.type === "keydown") {
    root.dispatchDocument("keydown", {
      shiftKey: Boolean(action.shiftKey),
      key: action.key,
      target: { tagName: "BODY", isContentEditable: false },
      preventDefault() {},
    });
  } else {
    throw new Error(`unknown action ${action.type}`);
  }
});

const activeTab = root.querySelector("[data-viewer-tab].is-active");
const activeStage = root.querySelector("[data-viewer-stage]:not([hidden])");
const activeDoc = activeStage ? activeStage.querySelector("[data-viewer-doc]") : null;
const imageError = activeStage
  ? activeStage.querySelector("[data-viewer-image-error]")
  : null;
const open = root.querySelector("[data-viewer-open]");
const get = root.querySelector("[data-viewer-get]");
const zoomLabel = root.querySelector("[data-viewer-zoom-label]");

function disabledState(selector) {
  return root.querySelectorAll(selector).map((element) => element.disabled);
}

process.stdout.write(
  JSON.stringify({
    activeTab: activeTab ? Number(activeTab.getAttribute("data-viewer-tab")) : null,
    stages: root.querySelectorAll("[data-viewer-stage]").map((element) => ({
      index: Number(element.getAttribute("data-viewer-stage")),
      hidden: element.hidden,
    })),
    controls: {
      rotate: disabledState("[data-viewer-rotate]"),
      zoom: disabledState("[data-viewer-zoom]"),
      reset: disabledState("[data-viewer-reset]"),
    },
    zoomLabel: zoomLabel ? zoomLabel.textContent.trim() : null,
    open: {
      href: open ? open.getAttribute("href") : null,
      hidden: open ? open.hidden : null,
    },
    get: {
      href: get ? get.getAttribute("href") : null,
      hidden: get ? get.hidden : null,
    },
    imageTransform: activeDoc ? activeDoc.style.transform || null : null,
    imageTransforms: root.querySelectorAll("[data-viewer-stage]").map((element) => {
      const image = element.querySelector("[data-viewer-doc]");
      return {
        index: Number(element.getAttribute("data-viewer-stage")),
        transform: image ? image.style.transform || null : null,
      };
    }),
    imageErrorHidden: imageError ? imageError.hidden : null,
    emptyState: Boolean(root.querySelector("[data-viewer-empty]")),
  })
);
