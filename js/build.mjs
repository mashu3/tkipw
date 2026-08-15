import * as esbuild from "esbuild";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
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

/** Packs share the core IIFE's ``window.__tkipwBase`` instead of bundling it. */
function jupyterWidgetsBaseExportNames() {
  const pkg = path.dirname(require.resolve("@jupyter-widgets/base/package.json"));
  const lib = path.join(pkg, "lib");
  const names = new Set();
  for (const file of fs.readdirSync(lib)) {
    if (!file.endsWith(".d.ts")) continue;
    const text = fs.readFileSync(path.join(lib, file), "utf8");
    for (const match of text.matchAll(
      /^export declare (?:class|function|const|let|var|enum|namespace) (\w+)/gm
    )) {
      names.add(match[1]);
    }
  }
  return [...names].filter((name) => /^[A-Za-z_$][\w$]*$/.test(name)).sort();
}

function jupyterWidgetsBaseExternalPlugin() {
  const named = jupyterWidgetsBaseExportNames()
    .map((name) => `export const ${name} = m[${JSON.stringify(name)}];`)
    .join("\n");
  const contents = `const m = globalThis.__tkipwBase;
if (!m) throw new Error("tkipw core is not loaded");
export default m;
${named}
`;
  return {
    name: "tkipw-base-external",
    setup(build) {
      build.onResolve({ filter: /^@jupyter-widgets\/base$/ }, () => ({
        path: "tkipw-base",
        namespace: "tkipw-external",
      }));
      build.onLoad({ filter: /.*/, namespace: "tkipw-external" }, () => ({
        contents,
        loader: "js",
      }));
    },
  };
}

const loaders = {
  ".css": "css",
  ".woff": "empty",
  ".woff2": "empty",
  ".ttf": "empty",
  ".eot": "empty",
  ".svg": "dataurl",
  ".png": "dataurl",
  ".gif": "dataurl",
};

const auditedFragments = [
  "node_modules/css-img-datauri-stream/",
  "node_modules/css-img-datauri-stream/node_modules/mime/",
  "node_modules/css-img-datauri-stream/node_modules/underscore/",
  "node_modules/elliptic/",
];

function assertNoAuditedInputs(metafile, label) {
  const bundledInputs = Object.keys(metafile.inputs);
  const included = auditedFragments.filter((fragment) =>
    bundledInputs.some((input) => input.includes(fragment))
  );
  if (included.length) {
    throw new Error(
      `Vulnerable build-only packages entered ${label}: ${included.join(", ")}`
    );
  }
}

async function stripFontFace(cssPath) {
  if (!fs.existsSync(cssPath)) {
    await fs.promises.writeFile(cssPath, "/* widgets css inlined into JS */\n");
    return;
  }
  let css = await fs.promises.readFile(cssPath, "utf8");
  css = css.replace(/@font-face\s*\{[^}]*\}/g, "/* font omitted */");
  await fs.promises.writeFile(cssPath, css);
}

function logBuilt(jsPath, cssPath) {
  const jsStat = fs.statSync(jsPath);
  const cssStat = fs.existsSync(cssPath) ? fs.statSync(cssPath) : { size: 0 };
  console.log(
    `built → ${path.basename(jsPath)} ${(jsStat.size / 1024).toFixed(0)}KB, ${path.basename(cssPath)} ${(cssStat.size / 1024).toFixed(0)}KB`
  );
}

await fs.promises.mkdir(outDir, { recursive: true });

const shared = {
  bundle: true,
  format: "iife",
  platform: "browser",
  target: ["es2020"],
  sourcemap: false,
  minify: true,
  loader: loaders,
  logLevel: "info",
  mainFields: ["browser", "module", "main"],
  conditions: ["import", "require", "default"],
  metafile: true,
};

const coreResult = await esbuild.build({
  ...shared,
  entryPoints: [path.join(__dirname, "src/index.js")],
  outfile: path.join(outDir, "runtime.js"),
  plugins: [anywidgetAmdPlugin],
});
assertNoAuditedInputs(coreResult.metafile, "runtime.js");
await stripFontFace(path.join(outDir, "runtime.css"));
logBuilt(path.join(outDir, "runtime.js"), path.join(outDir, "runtime.css"));

const packs = [
  {
    id: "leaflet",
    entry: "src/packs/leaflet.js",
    plugins: [cssTildePlugin, jupyterWidgetsBaseExternalPlugin()],
  },
  {
    id: "ipycanvas",
    entry: "src/packs/ipycanvas.js",
    plugins: [jupyterWidgetsBaseExternalPlugin()],
    banner: {
      js: "var global = typeof globalThis !== 'undefined' ? globalThis : window;",
    },
  },
  {
    id: "bqplot",
    entry: "src/packs/bqplot.js",
    plugins: [bqplotEsmPlugin, jupyterWidgetsBaseExternalPlugin()],
  },
  {
    id: "ipympl",
    entry: "src/packs/ipympl.js",
    plugins: [jupyterWidgetsBaseExternalPlugin()],
  },
];

for (const pack of packs) {
  const outfile = path.join(outDir, `pack-${pack.id}.js`);
  const result = await esbuild.build({
    ...shared,
    entryPoints: [path.join(__dirname, pack.entry)],
    outfile,
    plugins: pack.plugins,
    banner: pack.banner,
  });
  assertNoAuditedInputs(result.metafile, `pack-${pack.id}.js`);
  await stripFontFace(path.join(outDir, `pack-${pack.id}.css`));
  logBuilt(outfile, path.join(outDir, `pack-${pack.id}.css`));
}
