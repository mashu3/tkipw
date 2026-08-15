import * as base from "@jupyter-widgets/base";
import * as jupyterMatplotlib from "jupyter-matplotlib";
import "jupyter-matplotlib/css/mpl_widget.css";

// ipympl's MPLCanvasView.remove() only drops window listeners and skips
// ``super.remove()``, so clearing an Output leaves orphaned figure DOM
// (inline runs then look empty / stacked). Restore Lumino/DOM teardown.
(function patchIpymplCanvasRemove() {
  const View = jupyterMatplotlib.MPLCanvasView;
  if (!View || View.prototype.__tkipwPatchedRemove) return;
  const mplRemove = View.prototype.remove;
  View.prototype.remove = function tkipwMplCanvasRemove() {
    if (this.__tkipwRemoving) {
      return this;
    }
    this.__tkipwRemoving = true;
    try {
      if (this.__tkipwFitRO) {
        try {
          this.__tkipwFitRO.disconnect();
        } catch (e) {
          /* ignore */
        }
        this.__tkipwFitRO = null;
      }
      if (typeof mplRemove === "function") {
        mplRemove.apply(this, arguments);
      }
      try {
        return base.DOMWidgetView.prototype.remove.call(this);
      } catch (e) {
        if (this.el && this.el.parentNode) {
          this.el.remove();
        }
        return this;
      }
    } finally {
      this.__tkipwRemoving = false;
    }
  };
  View.prototype.__tkipwPatchedRemove = true;
})();

// Inline panes are often narrower than figsize pixels. Shrink via ipympl's
// own resize() so the bitmap matches the pane (CSS max-width would clip the
// absolutely-positioned canvas). Compact pop-ups are already sized to the
// figure — skip them.
(function patchIpymplFitWidth() {
  const View = jupyterMatplotlib.MPLCanvasView;
  if (!View || View.prototype.__tkipwPatchedFit) return;
  const mplRender = View.prototype.render;

  function hostWidth() {
    const host = document.getElementById("tkipw-widgets");
    return host ? Math.floor(host.clientWidth) : 0;
  }

  function fitIpymplView(view) {
    try {
      if (!view || !view.model || !view.el) return;
      if (document.body.classList.contains("tkipw-compact")) return;
      if (view.__tkipwFitting) return;
      const avail = hostWidth();
      if (avail < 64) return;
      const size = view.model.get("_size");
      if (!size || size[0] < 1 || size[1] < 1) return;
      if (size[0] <= avail + 1) return;
      view.__tkipwFitting = true;
      const height = Math.max(Math.round((size[1] * avail) / size[0]), 48);
      view.model.resize(avail, height);
      setTimeout(() => {
        view.__tkipwFitting = false;
      }, 150);
    } catch (e) {
      if (view) view.__tkipwFitting = false;
    }
  }

  function scheduleFit(view) {
    const run = () => fitIpymplView(view);
    requestAnimationFrame(() => {
      run();
      setTimeout(run, 80);
      setTimeout(run, 300);
    });
    // Do not hook change:_size — resize() updates _size and would loop.
    if (typeof ResizeObserver !== "undefined" && !view.__tkipwFitRO) {
      const host = document.getElementById("tkipw-widgets");
      if (host) {
        let timer = null;
        view.__tkipwFitRO = new ResizeObserver(() => {
          clearTimeout(timer);
          timer = setTimeout(run, 50);
        });
        view.__tkipwFitRO.observe(host);
      }
    }
  }

  View.prototype.render = function tkipwMplCanvasRender() {
    const result = mplRender.apply(this, arguments);
    const done = () => scheduleFit(this);
    Promise.resolve(result).then(done, done);
    return result;
  };
  View.prototype.__tkipwPatchedFit = true;
})();

window.__tkipwRegisterPack("jupyter-matplotlib", jupyterMatplotlib);
