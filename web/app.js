// Athrill Studio front end: boards, a run, its console, and the board's Devicetree.
"use strict";

const $ = (id) => document.getElementById(id);
const EDGE_COLORS = {
  interrupt: "#d1242f", dma: "#8250df", clock: "#1a7f37", reset: "#9a6700",
  gpio: "#0969da", pinctrl: "#6e7781", value: "#bf3989", pwm: "#fb8500", adc: "#57606a",
};
let boards = [];
let cy = null;
let models = {};          // DTB path -> the model Athrill built there
let logLines = 0;
const hidden = new Set(["clock"]);   // reference kinds not drawn (the clock tree is dense)

function applyHidden() {
  if (!cy) return;
  cy.edges().forEach((e) => e.style("display", hidden.has(e.data("kind")) ? "none" : "element"));
}

const term = new Terminal({ convertEol: true, fontSize: 13, scrollback: 5000,
  theme: matchMedia("(prefers-color-scheme: dark)").matches ? {} : { background: "#1d232b" } });
term.open($("terminal"));
fitTerminal();
addEventListener("resize", fitTerminal);

function fitTerminal() {
  const box = $("terminal").getBoundingClientRect();
  if (box.width === 0) return;
  const cols = Math.max(40, Math.floor(box.width / 7.8));
  const rows = Math.max(10, Math.floor(box.height / 17));
  term.resize(cols, rows);
}

// --- tabs
document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".tab, .panel").forEach((e) => e.classList.remove("active"));
  tab.classList.add("active");
  $(tab.dataset.tab).classList.add("active");
  if (tab.dataset.tab === "devicetree" && cy) { cy.resize(); runLayout(); }
  if (tab.dataset.tab === "console") fitTerminal();
  if (tab.dataset.tab === "flight" && window.onFlightTab) window.onFlightTab();
}));

// --- boards
async function loadBoards() {
  boards = await (await fetch("/api/boards")).json();
  $("board").innerHTML = boards.map((b) => `<option value="${b.id}">${b.title}</option>`).join("");
  $("board").addEventListener("change", selectBoard);
  $("firmware").addEventListener("change", updateButtons);
  selectBoard();
}

function currentBoard() { return boards.find((b) => b.id === $("board").value); }

function selectBoard() {
  const board = currentBoard();
  $("boardinfo").textContent = board.soc;
  $("firmware").innerHTML = board.firmware.length
    ? board.firmware.map((f) => `<option value="${f.id}">${f.title}${f.seconds ? ` (${f.seconds} s)` : ""}</option>`).join("")
    : `<option value="">no firmware yet (Devicetree only)</option>`;
  models = {};
  updateButtons();
  loadDevicetree(board.id);
}

function updateButtons(running) {
  const hasFirmware = currentBoard().firmware.length > 0;
  $("run").disabled = !hasFirmware;
  $("stop").disabled = !running;
}

// --- run
$("run").addEventListener("click", async () => {
  term.reset();
  $("log").textContent = ""; logLines = 0; $("logcount").textContent = "";
  models = {}; colorModels();
  const res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ board: $("board").value, firmware: $("firmware").value,
                           real_time: $("realtime").checked }) });
  if (!res.ok) term.write(`\x1b[31m${await res.text()}\x1b[0m\r\n`);
});
$("stop").addEventListener("click", () => fetch("/api/stop", { method: "POST" }));

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (event) => {
    const m = JSON.parse(event.data);
    if (m.type === "console") term.write(m.data);
    else if (m.type === "athrill") addLog(m.line);
    else if (m.type === "model" && m.board === $("board").value) { models[m.path] = m; colorModels(); }
    else if (m.type === "state") showState(m);
    else if (m.type === "progress") showProgress(m);
    else if (m.type === "flight" || m.type === "flight_status") window.onFlight && window.onFlight(m);
  };
  ws.onclose = () => setTimeout(connect, 1000);
}

function addLog(line) {
  logLines += 1;
  $("logcount").textContent = `(${logLines} lines)`;
  const log = $("log");
  log.textContent += line + "\n";
  log.scrollTop = log.scrollHeight;
}

// Virtual time and the real-time factor, from Athrill's PROGRESS reports:
// the RTF over the last second of wall time, and over the whole run.
let samples = [];
function showProgress(m) {
  samples.push(m);
  while (samples.length > 2 && m.wall_usec - samples[1].wall_usec > 1e6) samples.shift();
  const first = samples[0];
  const recent = m.wall_usec > first.wall_usec ? (m.virtual_usec - first.virtual_usec) / (m.wall_usec - first.wall_usec) : 0;
  const total = m.wall_usec > 0 ? m.virtual_usec / m.wall_usec : 0;
  $("meter").innerHTML = `virtual <b>${(m.virtual_usec / 1e6).toFixed(1)} s</b> · RTF <b>${recent.toFixed(2)}</b>`
    + ` <span title="over the whole run">(avg ${total.toFixed(2)})</span>`;
}

function showState(m) {
  const el = $("state");
  el.className = `state ${m.state}`;
  if (m.state === "running") {
    const limit = m.virtual_seconds ? `${m.virtual_seconds} s virtual` : "until Stop";
    el.textContent = `running ${m.firmware} (${limit}${m.real_time ? ", real time" : ""})`;
    samples = [];
    $("meter").textContent = "";
  }
  else if (m.state === "exited") {
    el.textContent = `exited (${m.wall_seconds} s wall)`;
    if (!samples.length) $("meter").textContent = "no virtual-time report (this athrill3 has no DEBUG_FUNC_PROGRESS_MSEC)";
  }
  else el.textContent = m.state;
  updateButtons(m.state === "running");
  window.onRunState && window.onRunState(m);
}

// --- Devicetree graph
async function loadDevicetree(id) {
  const res = await fetch(`/api/boards/${id}/devicetree`);
  if (!res.ok) { $("dtmodel").textContent = await res.text(); return; }
  const dt = await res.json();
  $("dtmodel").textContent = dt.model;
  const elements = [];
  for (const n of dt.nodes) {
    elements.push({ data: { id: n.path, label: n.path === "/" ? dt.model : n.name, node: n } });
    if (n.parent) elements.push({ data: { id: `bus:${n.path}`, source: n.parent, target: n.path, kind: "bus" } });
  }
  dt.edges.forEach((e, i) => elements.push({ data: { id: `ref:${i}`, source: e.from, target: e.to, kind: e.kind } }));
  if (cy) cy.destroy();
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  cy = cytoscape({
    container: $("graph"), elements, wheelSensitivity: 0.2,
    style: [
      { selector: "node", style: { label: "data(label)", "font-size": 11, color: dark ? "#e6edf3" : "#1d232b",
        "text-valign": "bottom", "text-margin-y": 3, width: 18, height: 18, shape: "round-rectangle",
        "background-color": dark ? "#3d4651" : "#c9d1d9" } },
      { selector: "node.modelled", style: { "background-color": "#1f6feb" } },
      { selector: "node:selected", style: { "border-width": 3, "border-color": "#fb8500" } },
      { selector: "edge", style: { width: 1, "curve-style": "bezier", "line-color": dark ? "#2d353f" : "#d8dde3" } },
      ...Object.entries(EDGE_COLORS).map(([kind, color]) => ({ selector: `edge[kind="${kind}"]`,
        style: { "line-color": color, "target-arrow-color": color, "target-arrow-shape": "triangle",
                 "arrow-scale": 0.6, width: 1.5, "line-style": "dashed", opacity: 0.75 } })),
    ],
  });
  if ($("devicetree").classList.contains("active")) runLayout();
  cy.on("tap", "node", (ev) => showDetail(ev.target.data("node")));
  $("legend").innerHTML = `<div><i class="node" style="background:#1f6feb"></i>model built by Athrill (from the last run)</div>`
    + `<div><i style="border-color:${dark ? "#2d353f" : "#d8dde3"};border-top-style:solid"></i>bus (parent → child)</div>`
    + Object.entries(EDGE_COLORS).map(([k, c]) => `<div><label><input type="checkbox" data-kind="${k}" ${hidden.has(k) ? "" : "checked"}>`
      + `<i style="border-color:${c};border-top-style:dashed"></i>${k}</label></div>`).join("");
  $("legend").querySelectorAll("input").forEach((box) => box.addEventListener("change", () => {
    if (box.checked) hidden.delete(box.dataset.kind); else hidden.add(box.dataset.kind);
    applyHidden();
  }));
  applyHidden();
  colorModels();
}

// The bus tree and the references both pull: devices cluster around the
// controllers they use (NVIC, DMA, RCC, GPIO ports). Laid out when the tab is
// visible, since a hidden container has no size.
function runLayout() {
  cy.layout({ name: "cose", animate: false, randomize: false, padding: 20, nodeRepulsion: () => 9000,
    idealEdgeLength: (e) => (e.data("kind") === "bus" ? 40 : 90),
    edgeElasticity: (e) => (e.data("kind") === "bus" ? 100 : 30), nodeDimensionsIncludeLabels: true,
    numIter: 2500 }).run();
  cy.fit(undefined, 20);
}

function colorModels() {
  if (!cy) return;
  cy.nodes().forEach((n) => n.toggleClass("modelled", Boolean(models[n.id()])));
}

function showDetail(n) {
  const m = models[n.path];
  const hex = (v) => "0x" + v.toString(16);
  const refs = cy.edges(`[source = "${n.path}"][kind != "bus"]`).map((e) => `${e.data("kind")} → ${e.target().id()}`);
  $("detail").innerHTML = `<p><b>${n.path}</b></p>`
    + `<p>compatible: <code>${n.compatible.join(", ") || "-"}</code></p>`
    + (n.reg.length ? `<p>reg: <code>${n.reg.map(hex).join(" ")}</code></p>` : "")
    + `<p>Athrill model: ${m ? `<code>${m.model}</code> (${m.provider}, matched ${m.compatible})` : "none (run the firmware to see the models)"}</p>`
    + (refs.length ? `<p>references:<br>${refs.map((r) => `<code>${r}</code>`).join("<br>")}</p>` : "");
}

loadBoards();
connect();
