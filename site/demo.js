const PYODIDE_VERSION = "0.26.2";
const PYODIDE_INDEX = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

const DRIVER_PY = [
  "import json",
  "from hyprvalidate.schema.extractor import Schema",
  "from hyprvalidate.hyprlang.parser import parse, ParseError",
  "from hyprvalidate.converter.mapper import convert_split",
  "from hyprvalidate import checker",
  "",
  "with open('/hv/schema.json') as f:",
  "    _schema = Schema.from_json(f.read())",
  "",
  "def run_demo(conf_text):",
  "    try:",
  "        hf = parse(conf_text)",
  "    except ParseError as exc:",
  "        return json.dumps({'error': 'parse', 'message': str(exc)})",
  "    except Exception as exc:",
  "        return json.dumps({'error': 'parse', 'message': str(exc)})",
  "",
  "    files = convert_split(_schema, hf)",
  "    out = {}",
  "    for name, src in files.items():",
  "        findings = [",
  "            {'line': f.line, 'kind': f.kind.value, 'message': f.message}",
  "            for f in checker.check_source(_schema, src)",
  "        ]",
  "        out[name] = {'source': src, 'findings': findings}",
  "    return json.dumps({'files': out})",
].join("\n");

function b64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = src;
    el.onload = resolve;
    el.onerror = () => reject(new Error(`failed to load ${src}`));
    document.head.appendChild(el);
  });
}

let readyPromise = null;

/**
 * Boots the Python runtime. Deliberately NOT called on page load: Pyodide is
 * ~10MB, and most visitors are here to read, not to run a conversion. It is
 * kicked off on the first Convert click instead.
 */
export function loadDemo(onStatus) {
  if (readyPromise) return readyPromise;

  readyPromise = (async () => {
    onStatus("downloading python runtime (~10MB, first run only)…");
    await loadScript(`${PYODIDE_INDEX}pyodide.js`);

    const pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX });

    onStatus("installing luaparser…");
    await pyodide.loadPackage("micropip");
    const micropip = pyodide.pyimport("micropip");
    await micropip.install("luaparser");

    onStatus("loading hyprvalidate…");
    const { PY_FILES, SCHEMA_JSON_B64 } = await import("./bundle.js");

    for (const dir of ["schema", "hyprlang", "luaast", "converter"]) {
      pyodide.FS.mkdirTree(`/hv/src/hyprvalidate/${dir}`);
    }
    for (const [relPath, b64] of Object.entries(PY_FILES)) {
      const withoutPrefix = relPath.replace(/^hyprvalidate\//, "");
      pyodide.FS.writeFile("/hv/src/hyprvalidate/" + withoutPrefix, b64ToBytes(b64));
    }
    pyodide.FS.writeFile("/hv/schema.json", b64ToBytes(SCHEMA_JSON_B64));
    pyodide.runPython("import sys; sys.path.insert(0, '/hv/src')");
    pyodide.runPython(DRIVER_PY);

    onStatus(null);
    return pyodide;
  })();

  return readyPromise;
}

export async function runConvert(confText) {
  const pyodide = await readyPromise;
  pyodide.globals.set("_input_conf", confText);
  const resultJson = pyodide.runPython("run_demo(_input_conf)");
  return JSON.parse(resultJson);
}
