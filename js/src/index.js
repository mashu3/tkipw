/**
 * tkwry IPC ↔ Jupyter widgets Comm adapter + HTMLManager host.
 */
import { HTMLManager } from "@jupyter-widgets/html-manager";
import * as base from "@jupyter-widgets/base";
import * as controls from "@jupyter-widgets/controls";
import * as jupyterLeaflet from "jupyter-leaflet";

// CSS for ipywidgets 8 controls
import "@jupyter-widgets/controls/css/widgets-base.css";
import "@jupyter-widgets/controls/css/labvariables.css";

// anywidget factory (AMD → ESM via build plugin)
import anywidgetFactory from "anywidget";

const anywidgetMod =
  typeof anywidgetFactory === "function"
    ? anywidgetFactory(base)
    : anywidgetFactory;

function postToPython(msg) {
  if (window.ipc && typeof window.ipc.postMessage === "function") {
    window.ipc.postMessage(JSON.stringify(msg));
  } else {
    console.warn("[tkipw] window.ipc unavailable", msg);
  }
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
    // Mimic kernel iopub status idle so WidgetModel pending msg counter clears
    if (callbacks && callbacks.iopub && callbacks.iopub.status) {
      try {
        callbacks.iopub.status({
          content: { execution_state: "idle" },
        });
      } catch (e) {
        /* ignore */
      }
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
        if (moduleName === "anywidget") {
          return Promise.resolve(anywidgetMod);
        }
        if (moduleName === "jupyter-leaflet") {
          return Promise.resolve(jupyterLeaflet);
        }
        return Promise.reject(
          new Error(`Unknown widget module: ${moduleName}`)
        );
      },
    });
    this.el = el;
    this._comms = new Map();
  }

  /**
   * Override to avoid runtime require() (broken inside an IIFE bundle).
   */
  loadClass(className, moduleName, moduleVersion) {
    return Promise.resolve()
      .then(() => {
        if (
          moduleName === "@jupyter-widgets/base" ||
          moduleName === "jupyter-js-widgets"
        ) {
          return base;
        }
        if (
          moduleName === "@jupyter-widgets/controls" ||
          moduleName === "jupyter-js-widgets"
        ) {
          return controls;
        }
        if (moduleName === "anywidget") {
          return anywidgetMod;
        }
        if (moduleName === "jupyter-leaflet") {
          return jupyterLeaflet;
        }
        if (this.loader) {
          return this.loader(moduleName, moduleVersion);
        }
        throw new Error(
          `Could not load module ${moduleName}@${moduleVersion}`
        );
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
    applyBuffersAsUint8(data, buffers);
    // WidgetModel._handle_comm_msg may return a Promise (async serializers).
    return Promise.resolve(comm.handle_msg(data, []));
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

  const mount = document.createElement("div");
  mount.id = "tkipw-widgets";
  root.appendChild(mount);

  const manager = new TkipwManager(mount);
  window.__tkipwManager = manager;
  window.__tkipwResizePlotly = () => resizePlotlyPlots(mount);

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
