/**
 * tkwry IPC ↔ Jupyter widgets Comm adapter + HTMLManager host.
 */
import { HTMLManager } from "@jupyter-widgets/html-manager";
import * as base from "@jupyter-widgets/base";
import * as controls from "@jupyter-widgets/controls";

// CSS for ipywidgets 8 controls
import "@jupyter-widgets/controls/css/widgets-base.css";
import "@jupyter-widgets/controls/css/labvariables.css";

// anywidget factory (AMD → ESM via build plugin)
import anywidgetFactory from "anywidget";

const anywidgetMod =
  typeof anywidgetFactory === "function"
    ? anywidgetFactory(base)
    : anywidgetFactory;

window.__tkipwBase = base;
window.__tkipwPackExports = window.__tkipwPackExports || {};
window.__tkipwRegisterPack = function tkipwRegisterPack(name, exports) {
  window.__tkipwPackExports[name] = exports;
};

const PACK_FOR_MODULE = {
  "jupyter-leaflet": "leaflet",
  ipycanvas: "ipycanvas",
  bqplot: "bqplot",
  bqscales: "bqplot",
  "jupyter-matplotlib": "ipympl",
};
const packPromises = {};

function lookupLoaded(moduleName) {
  switch (moduleName) {
    case "@jupyter-widgets/base":
    case "jupyter-js-widgets":
      return base;
    case "@jupyter-widgets/controls":
      return controls;
    case "anywidget":
      return anywidgetMod;
    default:
      return (window.__tkipwPackExports || {})[moduleName];
  }
}

function loadPackScript(url) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load widget pack: ${url}`));
    document.head.appendChild(script);
  });
}

function ensurePack(packId) {
  if (packPromises[packId]) {
    return packPromises[packId];
  }
  const urls = (window.__tkipwPackUrls || {})[packId];
  if (!urls || !urls.js) {
    return Promise.reject(new Error(`Unknown widget pack: ${packId}`));
  }
  packPromises[packId] = Promise.resolve()
    .then(() => {
      if (urls.css) {
        injectWidgetStyles({ [packId]: { style: urls.css } });
      }
      return loadPackScript(urls.js);
    })
    .catch((err) => {
      delete packPromises[packId];
      throw err;
    });
  return packPromises[packId];
}

function loadBundledModule(moduleName) {
  const loaded = lookupLoaded(moduleName);
  if (loaded) {
    return Promise.resolve(loaded);
  }
  const packId = PACK_FOR_MODULE[moduleName];
  if (!packId) {
    return Promise.reject(new Error(`Unknown widget module: ${moduleName}`));
  }
  return ensurePack(packId).then(() => {
    const mod = lookupLoaded(moduleName);
    if (!mod) {
      throw new Error(`Pack ${packId} did not register ${moduleName}`);
    }
    return mod;
  });
}

const amdLoads = new Map();
let amdShimInstalled = false;
let lastAmdModule;
let lastAmdName;

function resolveAmdDep(id) {
  const bundled = lookupLoaded(id);
  if (bundled !== undefined) {
    return bundled;
  }
  if (Object.prototype.hasOwnProperty.call(window, id) && window[id]) {
    return window[id];
  }
  return undefined;
}

function installAmdShim() {
  if (amdShimInstalled) {
    return;
  }
  amdShimInstalled = true;
  const requireFn = function amdRequire(id) {
    if (Array.isArray(id)) {
      throw new Error("async AMD require() is not supported");
    }
    const resolved = resolveAmdDep(id);
    if (resolved === undefined) {
      throw new Error(`AMD missing dependency: ${id}`);
    }
    return resolved;
  };
  if (typeof window.require !== "function") {
    window.require = requireFn;
  }
  window.define = function amdDefine(name, deps, factory) {
    if (typeof name !== "string") {
      factory = deps;
      deps = name;
      name = null;
    }
    if (!Array.isArray(deps)) {
      factory = deps;
      deps = [];
    }
    const specials = {};
    const args = deps.map((dep) => {
      if (dep === "exports") {
        specials.exports = specials.exports || {};
        return specials.exports;
      }
      if (dep === "module") {
        specials.module = specials.module || { exports: {} };
        return specials.module;
      }
      if (dep === "require") {
        return requireFn;
      }
      const resolved = resolveAmdDep(dep);
      if (resolved === undefined) {
        throw new Error(`AMD missing dependency: ${dep}`);
      }
      return resolved;
    });
    let result;
    if (typeof factory === "function") {
      result = factory.apply(null, args);
    } else {
      result = factory;
    }
    if (result === undefined) {
      result =
        (specials.module && specials.module.exports) || specials.exports;
    }
    lastAmdModule = result;
    lastAmdName = name;
    if (name) {
      window[name] = result;
    }
  };
  window.define.amd = {};
}

function injectWidgetStyles(registry) {
  if (!registry) {
    return;
  }
  for (const spec of Object.values(registry)) {
    const url = spec && spec.style;
    if (!url) {
      continue;
    }
    const attr = "data-tkipw-widget-style";
    const already = Array.prototype.some.call(
      document.querySelectorAll(`link[${attr}]`),
      (el) => el.getAttribute(attr) === url
    );
    if (already) {
      continue;
    }
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = url;
    link.setAttribute(attr, url);
    document.head.appendChild(link);
  }
}

function loadAmdScript(moduleName, spec) {
  return new Promise((resolve, reject) => {
    installAmdShim();
    if (spec.publicPath) {
      window.__webpack_public_path__ = spec.publicPath;
    }
    lastAmdModule = undefined;
    lastAmdName = undefined;
    const script = document.createElement("script");
    script.src = spec.url;
    script.async = true;
    script.onload = () => {
      const mod = lastAmdModule;
      if (mod && typeof mod === "object") {
        resolve(mod);
        return;
      }
      const named = lastAmdName && window[lastAmdName];
      if (named) {
        resolve(named);
        return;
      }
      if (window[moduleName]) {
        resolve(window[moduleName]);
        return;
      }
      reject(
        new Error(`AMD module ${moduleName} did not call define(): ${spec.url}`)
      );
    };
    script.onerror = () => {
      reject(new Error(`Failed to load widget module ${moduleName}: ${spec.url}`));
    };
    document.head.appendChild(script);
  });
}

function loadRegisteredAmd(moduleName) {
  const registry = window.__tkipwWidgetModules || {};
  const spec = registry[moduleName];
  if (!spec || !spec.url) {
    return Promise.reject(new Error(`Unknown widget module: ${moduleName}`));
  }
  const cached = amdLoads.get(spec.url);
  if (cached) {
    return cached;
  }
  const loading = loadAmdScript(moduleName, spec).catch((err) => {
    amdLoads.delete(spec.url);
    throw err;
  });
  amdLoads.set(spec.url, loading);
  return loading;
}

function postToPython(msg) {
  if (window.ipc && typeof window.ipc.postMessage === "function") {
    window.ipc.postMessage(JSON.stringify(msg));
  } else {
    console.warn("[tkipw] window.ipc unavailable", msg);
  }
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

/**
 * Desktop WebViews ignore ``<a download>``. Bridge those clicks to Python so
 * tkipw can show a native save dialog (bqplot toolbar Save, etc.).
 */
function installDownloadBridge() {
  const originalClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function patchedAnchorClick(...args) {
    const filename = this.getAttribute("download");
    const href = this.href || "";
    if (filename == null || filename === "" || !href) {
      return originalClick.apply(this, args);
    }
    if (href.startsWith("data:")) {
      const comma = href.indexOf(",");
      if (comma < 0) {
        return originalClick.apply(this, args);
      }
      const header = href.slice(5, comma);
      const payload = href.slice(comma + 1);
      const mime = (header.split(";")[0] || "application/octet-stream").trim();
      const isBase64 = /;base64/i.test(header);
      const data_base64 = isBase64
        ? payload
        : bytesToBase64(new TextEncoder().encode(decodeURIComponent(payload)));
      postToPython({
        channel: "download",
        filename,
        mime,
        data_base64,
      });
      return;
    }
    if (href.startsWith("blob:")) {
      fetch(href)
        .then((r) => r.arrayBuffer())
        .then((buf) => {
          postToPython({
            channel: "download",
            filename,
            mime: "application/octet-stream",
            data_base64: bytesToBase64(new Uint8Array(buf)),
          });
        })
        .catch((e) => {
          console.error("[tkipw] blob download failed", e);
          originalClick.apply(this, args);
        });
      return;
    }
    return originalClick.apply(this, args);
  };
}

function decodeBuffers(b64list) {
  if (!b64list || !b64list.length) return [];
  return b64list.map((b64) => {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  });
}

/**
 * Place binary buffers into state as Uint8Array.
 * WKWebView's Blob() mishandles DataView (empty image); Uint8Array works.
 * Clears buffer_paths so WidgetModel.put_buffers won't convert back to DataView.
 */
function applyBuffersAsUint8(data, buffers) {
  if (!data || !data.state) return;
  const paths = data.buffer_paths || [];
  if (!paths.length) return;
  const bufs = buffers || [];
  for (let i = 0; i < paths.length; i++) {
    const path = paths[i];
    let buffer = bufs[i];
    let bytes;
    if (buffer instanceof Uint8Array) {
      bytes = buffer;
    } else if (buffer instanceof ArrayBuffer) {
      bytes = new Uint8Array(buffer);
    } else if (ArrayBuffer.isView(buffer)) {
      bytes = new Uint8Array(
        buffer.buffer,
        buffer.byteOffset,
        buffer.byteLength
      );
    } else {
      continue;
    }
    let obj = data.state;
    for (let j = 0; j < path.length - 1; j++) {
      obj = obj[path[j]];
    }
    obj[path[path.length - 1]] = bytes;
  }
  data.buffer_paths = [];
}

function encodeBuffers(buffers) {
  if (!buffers || !buffers.length) return [];
  return buffers.map((buf) => {
    const bytes =
      buf instanceof ArrayBuffer
        ? new Uint8Array(buf)
        : buf instanceof Uint8Array
          ? buf
          : new Uint8Array(buf.buffer || buf);
    let s = "";
    for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s);
  });
}

/** Classic Comm that talks to Python over tkwry IPC. */
class IpcComm {
  constructor(comm_id, target_name = "jupyter.widget") {
    this.comm_id = comm_id;
    this.target_name = target_name;
    this._msg = null;
    this._close = null;
  }

  open() {
    return "";
  }

  close() {
    postToPython({
      channel: "comm",
      msg_type: "comm_close",
      comm_id: this.comm_id,
      data: {},
    });
  }

  send(data, callbacks, metadata, buffers) {
    postToPython({
      channel: "comm",
      msg_type: "comm_msg",
      comm_id: this.comm_id,
      data: data || {},
      metadata: metadata || {},
      buffers: encodeBuffers(buffers),
    });
    // Mimic kernel iopub status idle so WidgetModel pending msg counter clears.
    // Must run *after* send_sync_message returns and increments `_pending_msgs`;
    // a synchronous idle here decrements first (→ -1) and leaves the counter
    // stuck at 1, so later trait updates are buffered forever (bqplot PanZoom).
    if (callbacks && callbacks.iopub && callbacks.iopub.status) {
      const status = callbacks.iopub.status;
      queueMicrotask(() => {
        try {
          status({
            content: { execution_state: "idle" },
          });
        } catch (e) {
          /* ignore */
        }
      });
    }
    return this.comm_id;
  }

  on_msg(cb) {
    this._msg = cb;
  }

  on_close(cb) {
    this._close = cb;
  }

  /** Deliver a Python→JS message into the model. */
  handle_msg(data, buffers) {
    if (this._msg) {
      return this._msg({
        content: { data, comm_id: this.comm_id },
        // Prefer Uint8Array so ImageView → Blob works under WKWebView.
        buffers: (buffers || []).map((b) => {
          if (b instanceof Uint8Array) return b;
          if (b instanceof ArrayBuffer) return new Uint8Array(b);
          if (ArrayBuffer.isView(b)) {
            return new Uint8Array(b.buffer, b.byteOffset, b.byteLength);
          }
          return b;
        }),
      });
    }
  }

  handle_close(data) {
    if (this._close) {
      return this._close({ content: { data, comm_id: this.comm_id } });
    }
  }
}

class TkipwManager extends HTMLManager {
  constructor(el) {
    super({
      loader: (moduleName) => {
        return loadBundledModule(moduleName).catch(() =>
          loadRegisteredAmd(moduleName)
        );
      },
    });
    this.el = el;
    this._comms = new Map();
  }

  /**
   * Override to avoid runtime require() (broken inside an IIFE bundle).
   * Registered AMD/nbextension modules are loaded from the loopback host.
   */
  loadClass(className, moduleName, moduleVersion) {
    return Promise.resolve()
      .then(() => {
        const loaded = lookupLoaded(moduleName);
        if (loaded) {
          return loaded;
        }
        if (PACK_FOR_MODULE[moduleName]) {
          return loadBundledModule(moduleName);
        }
        return loadRegisteredAmd(moduleName);
      })
      .then((mod) => {
        if (mod && mod[className]) {
          return mod[className];
        }
        throw new Error(
          `Class ${className} not found in module ${moduleName}@${moduleVersion}`
        );
      });
  }

  async _create_comm(target_name, model_id, data, metadata, buffers) {
    const id = model_id || base.uuid();
    let comm = this._comms.get(id);
    if (!comm) {
      comm = new IpcComm(id, target_name);
      this._comms.set(id, comm);
    }
    // Kernel-initiated opens are handled separately; frontend-initiated opens
    // notify Python (rare in tkipw — widgets are created in Python first).
    if (data !== undefined) {
      postToPython({
        channel: "comm",
        msg_type: "comm_open",
        comm_id: id,
        target_name,
        data: data || {},
        metadata: metadata || {},
        buffers: encodeBuffers(buffers),
      });
    }
    return comm;
  }

  _get_comm_info() {
    const comms = {};
    for (const id of this._comms.keys()) {
      comms[id] = { target_name: "jupyter.widget" };
    }
    return Promise.resolve(comms);
  }

  async handlePythonCommOpen(msg) {
    const comm_id = msg.comm_id;
    let comm = this._comms.get(comm_id);
    if (!comm) {
      comm = new IpcComm(comm_id, msg.target_name || "jupyter.widget");
      this._comms.set(comm_id, comm);
    }
    const data = msg.data || {};
    const buffers = decodeBuffers(msg.buffers);
    applyBuffersAsUint8(data, buffers);
    try {
      await this.handle_comm_open(comm, {
        content: {
          comm_id,
          data,
          target_name: msg.target_name || "jupyter.widget",
        },
        metadata: msg.metadata || {},
        buffers: [],
      });
    } catch (e) {
      console.error("[tkipw] handle_comm_open failed", comm_id, e);
      throw e;
    }
  }

  handlePythonCommMsg(msg) {
    const comm = this._comms.get(msg.comm_id);
    if (!comm) return;
    const data = msg.data || {};
    const buffers = decodeBuffers(msg.buffers);
    const paths = data.buffer_paths || [];
    if (paths.length) {
      // Trait updates: install Uint8Array into state (WKWebView-safe) and
      // clear buffer_paths so WidgetModel won't convert back to DataView.
      applyBuffersAsUint8(data, buffers);
      return Promise.resolve(comm.handle_msg(data, []));
    }
    // Custom messages (ipycanvas draw commands, etc.) pass naked buffers.
    return Promise.resolve(
      comm.handle_msg(
        data,
        buffers.map((b) => {
          if (b instanceof Uint8Array) return b;
          if (b instanceof ArrayBuffer) return new Uint8Array(b);
          if (ArrayBuffer.isView(b)) {
            return new Uint8Array(b.buffer, b.byteOffset, b.byteLength);
          }
          return b;
        })
      )
    );
  }

  handlePythonCommClose(msg) {
    const comm = this._comms.get(msg.comm_id);
    if (!comm) return;
    const result = Promise.resolve(comm.handle_close(msg.data || {}));
    this._comms.delete(msg.comm_id);
    return result;
  }

  async displayModels(model_ids) {
    for (const model_id of model_ids) {
      const model = await this.get_model(model_id);
      const view = await this.create_view(model);
      await this.display_view(view, this.el);
    }
    // Plotly defaults to a fixed ~700px width; fit to the host pane.
    schedulePlotlyResize(this.el);
  }
}

function resizePlotlyPlots(root) {
  const Plotly = window.Plotly;
  if (!Plotly || !Plotly.Plots || !root) return;
  root.querySelectorAll(".js-plotly-plot").forEach((el) => {
    try {
      Plotly.Plots.resize(el);
    } catch (e) {
      /* ignore */
    }
  });
}

function schedulePlotlyResize(root) {
  // newPlot is async; resize once the SVG exists and again on the next frame.
  requestAnimationFrame(() => {
    resizePlotlyPlots(root);
    requestAnimationFrame(() => resizePlotlyPlots(root));
  });
  setTimeout(() => resizePlotlyPlots(root), 50);
  setTimeout(() => resizePlotlyPlots(root), 250);
}

export async function boot() {
  const root = document.getElementById("tkipw-root");
  const status = document.getElementById("tkipw-status");
  if (status) status.remove();

  installDownloadBridge();

  const mount = document.createElement("div");
  mount.id = "tkipw-widgets";
  root.appendChild(mount);

  const manager = new TkipwManager(mount);
  window.__tkipwManager = manager;
  window.__tkipwResizePlotly = () => resizePlotlyPlots(mount);
  injectWidgetStyles(window.__tkipwWidgetModules);

  if (typeof ResizeObserver !== "undefined") {
    let resizeTimer = null;
    const ro = new ResizeObserver(() => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => resizePlotlyPlots(mount), 50);
    });
    ro.observe(mount);
  }

  // Serialize delivery so display never races ahead of nested comm_open,
  // and so async state updates (e.g. Plotly ``_widget_data``) finish before
  // ``display`` creates views that snapshot model state at render time.
  let _chain = Promise.resolve();
  window.__tkipwDeliver = function (payload) {
    _chain = _chain.then(async () => {
      let msg;
      try {
        msg = typeof payload === "string" ? JSON.parse(payload) : payload;
      } catch (e) {
        console.error("[tkipw] bad payload", e);
        return;
      }
      try {
        if (msg.channel === "comm") {
          if (msg.msg_type === "comm_open") {
            await manager.handlePythonCommOpen(msg);
          } else if (msg.msg_type === "comm_msg") {
            await Promise.resolve(manager.handlePythonCommMsg(msg));
          } else if (msg.msg_type === "comm_close") {
            await Promise.resolve(manager.handlePythonCommClose(msg));
          }
        } else if (msg.channel === "display") {
          await manager.displayModels(msg.model_ids || []);
        } else if (msg.channel === "widget_modules") {
          window.__tkipwWidgetModules = msg.modules || {};
          injectWidgetStyles(window.__tkipwWidgetModules);
        }
      } catch (e) {
        console.error("[tkipw] deliver error", e);
        postToPython({
          channel: "error",
          message: String(e && e.message ? e.message : e),
          detail: String(e && e.stack ? e.stack : e),
        });
      }
    });
    return _chain;
  };

  // Keep references so tree-shaking does not drop controls registration paths
  void controls;
  void base;

  postToPython({ channel: "ready" });
}

boot().catch((e) => {
  console.error(e);
  postToPython({
    channel: "error",
    message: String(e && e.message ? e.message : e),
    detail: String(e && e.stack ? e.stack : e),
  });
});
