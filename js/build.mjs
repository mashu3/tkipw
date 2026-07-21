import * as esbuild from "esbuild";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(__dirname, "../src/tkipw/html");

/** Convert anywidget's AMD entry into an ESM default export (the factory). */
const anywidgetAmdPlugin = {
  name: "anywidget-amd",
  setup(build) {
    build.onLoad({ filter: /anywidget[\\/]dist[\\/]index\.js$/ }, async (args) => {
      let code = await fs.promises.readFile(args.path, "utf8");
      code = code.replace(
        /define\(\["@jupyter-widgets\/base"\],\s*widget_default\);?\s*$/m,
        "export default widget_default;"
      );
      if (!code.includes("export default widget_default")) {
        throw new Error("Failed to rewrite anywidget AMD define()");
      }
      return { contents: code, loader: "js", resolveDir: path.dirname(args.path) };
    });
  },
};

/** Resolve webpack-style CSS url(~package/path) imports used by Leaflet. */
const cssTildePlugin = {
  name: "css-tilde",
  setup(build) {
    build.onResolve({ filter: /^~/ }, (args) => ({
      path: path.resolve(__dirname, "node_modules", args.path.slice(1)),
    }));
  },
};

/** Prefer ESM ``lib/`` entry points over webpack AMD ``browser``/``dist`` builds. */
const bqplotEsmPlugin = {
  name: "bqplot-esm",
  setup(build) {
    build.onResolve({ filter: /^bqplot$/ }, () => ({
      path: path.resolve(__dirname, "node_modules/bqplot/lib/index.js"),
    }));
    build.onResolve({ filter: /^bqscales$/ }, () => ({
      path: path.resolve(__dirname, "node_modules/bqscales/lib/index.js"),
    }));
  },
};

await fs.promises.mkdir(outDir, { recursive: true });

const buildResult = await esbuild.build({
  entryPoints: [path.join(__dirname, "src/index.js")],
  bundle: true,
  outfile: path.join(outDir, "runtime.js"),
  format: "iife",
  platform: "browser",
  target: ["es2020"],
  sourcemap: false,
  minify: true,
  banner: {
    js: [
      "var __webpack_public_path__ = __webpack_public_path__ || '';",
      // ipycanvas → buffer expects Node's ``global`` in the browser bundle.
      "var global = typeof globalThis !== 'undefined' ? globalThis : window;",
    ].join(" "),
  },
  loader: {
    ".css": "css",
    ".woff": "empty",
    ".woff2": "empty",
    ".ttf": "empty",
    ".eot": "empty",
    ".svg": "dataurl",
    ".png": "dataurl",
    ".gif": "dataurl",
  },
  plugins: [anywidgetAmdPlugin, cssTildePlugin, bqplotEsmPlugin],
  logLevel: "info",
  mainFields: ["browser", "module", "main"],
  conditions: ["import", "require", "default"],
  metafile: true,
});

const cssPath = path.join(outDir, "runtime.css");
if (!fs.existsSync(cssPath)) {
  await fs.promises.writeFile(cssPath, "/* widgets css inlined into runtime.js */\n");
} else {
  // Strip @font-face blocks that reference missing fonts
  let css = await fs.promises.readFile(cssPath, "utf8");
  css = css.replace(/@font-face\s*\{[^}]*\}/g, "/* font omitted */");
  await fs.promises.writeFile(cssPath, css);
}

const jsStat = fs.statSync(path.join(outDir, "runtime.js"));
const cssStat = fs.statSync(cssPath);
console.log(
  `built → runtime.js ${(jsStat.size / 1024).toFixed(0)}KB, runtime.css ${(cssStat.size / 1024).toFixed(0)}KB`
);

const bundledInputs = Object.keys(buildResult.metafile.inputs);
const auditedFragments = [
  "node_modules/css-img-datauri-stream/",
  "node_modules/css-img-datauri-stream/node_modules/mime/",
  "node_modules/css-img-datauri-stream/node_modules/underscore/",
  "node_modules/elliptic/",
];
const includedAuditedPackages = auditedFragments.filter((fragment) =>
  bundledInputs.some((input) => input.includes(fragment))
);
if (includedAuditedPackages.length) {
  throw new Error(
    `Vulnerable build-only packages unexpectedly entered the browser bundle: ${includedAuditedPackages.join(", ")}`
  );
}
