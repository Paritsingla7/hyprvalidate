import { loadDemo, runConvert } from "./demo.js";

const SAMPLE = [
  "$mainMod = SUPER",
  "",
  "monitor=eDP-1,1920x1080@144,0x0,1",
  "",
  "bind = $mainMod, Q, killactive,",
  "bindr = $mainMod, R, exec, hyprctl reload",
  "",
  "general {",
  "    gaps_in = 5",
  "    resize_on_border = true",
  "}",
  "",
  "animations {",
  "    enabled = yes, please :)",
  "}",
  "",
  "windowrule {",
  "    name = float-picker",
  "    match:class = pavucontrol",
  "    float = true",
  "}",
  "",
].join("\n");

const textarea = document.getElementById("demo-textarea");
const runBtn = document.getElementById("demo-run");
const statusEl = document.getElementById("demo-status");
const tabsEl = document.getElementById("demo-tabs");
const bodyEl = document.getElementById("demo-body");

textarea.value = SAMPLE;
statusEl.textContent = "";

let currentFiles = null;
let currentActive = null;

function setStatus(text, isError) {
  statusEl.textContent = text || "";
  statusEl.classList.toggle("err", !!isError);
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

function renderFile(name) {
  currentActive = name;
  for (const btn of tabsEl.children) {
    btn.setAttribute("aria-selected", btn.dataset.name === name ? "true" : "false");
  }
  const file = currentFiles[name];
  const lines = file.source.split("\n");
  const codeHtml = lines
    .map((l, i) => '<span class="ln">' + (i + 1) + "</span>" + escapeHtml(l))
    .join("\n");

  const findingsHtml = file.findings.length
    ? file.findings
        .map(
          (f) =>
            '<div class="f-item"><span class="loc">L' +
            (f.line ?? "?") +
            "</span><span>[" +
            f.kind +
            "] " +
            escapeHtml(f.message) +
            "</span></div>"
        )
        .join("")
    : '<div class="f-empty">no issues found</div>';

  bodyEl.innerHTML =
    '<pre class="code">' +
    codeHtml +
    '</pre><div class="findings">' +
    findingsHtml +
    "</div>";
}

function renderResult(result) {
  if (result.error) {
    tabsEl.hidden = true;
    bodyEl.innerHTML =
      '<div class="demo-placeholder">Couldn\'t parse that as hyprlang: ' +
      escapeHtml(result.message) +
      "</div>";
    return;
  }

  currentFiles = result.files;
  const names = Object.keys(currentFiles);
  tabsEl.hidden = false;
  tabsEl.innerHTML = names
    .map((name) => {
      const hasFindings = currentFiles[name].findings.length > 0;
      return (
        '<button class="file-tab" role="tab" data-name="' +
        name +
        '" aria-selected="false">' +
        name +
        (hasFindings ? '<span class="dot" title="has findings"></span>' : "") +
        "</button>"
      );
    })
    .join("");

  for (const btn of tabsEl.children) {
    btn.addEventListener("click", () => renderFile(btn.dataset.name));
  }

  const firstWithFindings = names.find((n) => currentFiles[n].findings.length > 0);
  renderFile(firstWithFindings || names[0]);
}

async function runNow() {
  runBtn.disabled = true;
  try {
    // First click pays for the runtime download; later clicks are instant.
    await loadDemo(setStatus);
    setStatus("converting…");
    const result = await runConvert(textarea.value);
    renderResult(result);
    setStatus("done");
  } catch (err) {
    setStatus("error: " + err.message, true);
  }
  runBtn.disabled = false;
}

runBtn.addEventListener("click", runNow);
