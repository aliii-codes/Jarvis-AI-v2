"use strict";
// Chat surface. Python drives it through the `bridge` QObject (see aura/ui.py).

const $ = (sel) => document.querySelector(sel);
const thread = $("#thread"), scroller = $("#scroll"), welcome = $("#welcome");
const input = $("#input"), sendBtn = $("#send"), newChatBtn = $("#new-chat"), statusEl = $("#status");

let bridge = null;
let busy = false;
let stick = true;   // follow new content unless the user scrolled up
let turn = null;    // the assistant reply currently streaming

marked.setOptions({ gfm: true, breaks: true });

const ICONS = {
  copy: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  send: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>',
  stop: '<svg viewBox="0 0 24 24" width="14" height="14"><rect x="5" y="5" width="14" height="14" rx="2.5" fill="currentColor"/></svg>',
  check: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
};

function el(tag, cls, html) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html !== undefined) node.innerHTML = html;
  return node;
}

// ── scrolling ─────────────────────────────────────────────────
scroller.addEventListener("scroll", () => {
  stick = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
  $(".topbar").classList.toggle("scrolled", scroller.scrollTop > 4);
});
function follow(force) {
  if (force || stick) scroller.scrollTop = scroller.scrollHeight;
}

// ── rendering ─────────────────────────────────────────────────
function copyButton(getText, label) {
  const btn = el("button", "action", ICONS.copy + (label ? `<span>${label}</span>` : ""));
  btn.type = "button";
  btn.addEventListener("click", () => {
    bridge && bridge.copyText(getText());
    btn.innerHTML = ICONS.check + "<span>Copied</span>";
    setTimeout(() => { btn.innerHTML = ICONS.copy + (label ? `<span>${label}</span>` : ""); }, 1400);
  });
  return btn;
}

function renderMarkdown(target, text) {
  target.innerHTML = DOMPurify.sanitize(marked.parse(text));
  target.querySelectorAll("pre > code").forEach((code) => {
    const pre = code.parentElement;
    const lang = ((code.className || "").match(/language-([\w+#-]+)/) || [])[1] || "";
    try {
      if (lang && hljs.getLanguage(lang)) hljs.highlightElement(code);
      else code.innerHTML = hljs.highlightAuto(code.textContent).value;
    } catch (e) { /* plain text is fine */ }
    const block = el("div", "codeblock");
    const head = el("div", "code-head", `<span>${lang || "code"}</span>`);
    head.appendChild(copyButton(() => code.textContent, "Copy"));
    pre.replaceWith(block);
    block.append(head, pre);
  });
}

function hideWelcome() { welcome.hidden = true; }

function showWelcome() {
  const hour = new Date().getHours();
  const part = hour < 5 ? "evening" : hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  $("#greeting").textContent = `Good ${part}, ${window.USER_NAME || "there"}`;
  welcome.hidden = false;
}

function addUser(text) {
  hideWelcome();
  const row = el("div", "msg user");
  const bubble = el("div", "bubble");
  bubble.textContent = text;
  row.appendChild(bubble);
  thread.appendChild(row);
  follow(true);
}

function addAssistant(text) {
  const row = el("div", "msg assistant");
  const content = el("div", "content");
  renderMarkdown(content, text);
  row.append(content, actionsFor(() => text));
  thread.appendChild(row);
}

function actionsFor(getText) {
  const actions = el("div", "actions");
  actions.appendChild(copyButton(getText, "Copy"));
  return actions;
}

function addNote(text, sub, kind) {
  hideWelcome();
  const note = el("div", "note" + (kind ? " " + kind : ""));
  const icon = el("span", "note-icon");
  icon.textContent = kind === "error" ? "⚠️" : "⏰";
  const body = el("div");
  body.appendChild(document.createTextNode(text));
  if (sub) { const s = el("div", "note-sub"); s.textContent = sub; body.appendChild(s); }
  note.append(icon, body);
  thread.appendChild(note);
  follow(true);
}

// ── a streaming assistant turn ───────────────────────────────
function startTurn() {
  const row = el("div", "msg assistant");
  const body = el("div", "body");
  const typing = el("div", "typing", "<span></span><span></span><span></span>");
  row.append(body, typing);
  thread.appendChild(row);
  turn = { row, body, typing, segment: null, chips: [], texts: [], renderQueued: false };
  follow(true);
}

function chipLabel(chip, text) {
  chip.node.querySelector(".label").textContent = chip.count > 1 ? `${text} ×${chip.count}` : text;
}

function settleChips() {
  turn.chips.forEach((c) => {
    if (!c.node.classList.contains("done")) {
      c.node.classList.add("done");
      chipLabel(c, c.done);
    }
  });
}

function onToken(text) {
  if (!turn) startTurn();
  turn.typing.hidden = true;
  if (!turn.segment) {
    settleChips();
    turn.segment = { node: el("div", "content"), text: "" };
    turn.body.appendChild(turn.segment.node);
    turn.texts.push(turn.segment);
  }
  turn.segment.text += text;
  if (!turn.renderQueued) {
    turn.renderQueued = true;
    requestAnimationFrame(() => {
      if (!turn) return;
      turn.renderQueued = false;
      if (turn.segment) renderMarkdown(turn.segment.node, turn.segment.text);
      follow();
    });
  }
  setStatus("typing…", true);
}

function onTool(name, running, done) {
  if (!turn) startTurn();
  settleChips();
  turn.segment = null;  // text after the tool starts a new block below the chip
  let tray = turn.body.lastElementChild;
  if (!tray || !tray.classList.contains("tools")) {
    tray = el("div", "tools");
    turn.body.appendChild(tray);
  }
  // Repeated tools share one chip with a count ("Searched the web ×3") instead of piling up.
  let chip = turn.chips.find((c) => c.name === name && tray.contains(c.node));
  if (chip) {
    chip.count += 1;
    chip.node.classList.remove("done");
  } else {
    const node = el("span", "chip",
      `<span class="spin"></span><span class="check">${ICONS.check}</span><span class="label"></span>`);
    tray.appendChild(node);
    chip = { name, node, done, count: 1 };
    turn.chips.push(chip);
  }
  chipLabel(chip, running);
  turn.typing.hidden = true;
  setStatus(running.toLowerCase(), true);
  follow();
}

function onTurnDone(stopped) {
  if (turn) {
    settleChips();
    if (stopped) turn.body.appendChild(el("div", "stopped", "Stopped"));
    turn.texts.forEach((s) => renderMarkdown(s.node, s.text));
    turn.typing.remove();
    const full = turn.texts.map((s) => s.text).join("\n\n").trim();
    if (full) turn.row.appendChild(actionsFor(() => full));
    if (!turn.body.children.length) turn.row.remove();
    turn = null;
  }
  setBusy(false);
  follow();
}

// ── composer ──────────────────────────────────────────────────
function setStatus(label, isBusy) {
  statusEl.querySelector(".label").textContent = label;
  statusEl.classList.toggle("busy", !!isBusy);
}

function setBusy(value) {
  busy = value;
  newChatBtn.disabled = value;
  // While busy, the send button becomes Stop.
  sendBtn.innerHTML = value ? ICONS.stop : ICONS.send;
  sendBtn.classList.toggle("stop", value);
  sendBtn.setAttribute("aria-label", value ? "Stop" : "Send");
  sendBtn.title = value ? "Stop (Esc)" : "Send";
  updateSend();
  if (!value) { setStatus("ready", false); input.focus(); }
}

function updateSend() { sendBtn.disabled = !busy && !input.value.trim(); }

function stop() {
  if (!busy || !bridge) return;
  bridge.stop();
  setStatus("stopping…", true);
}

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 220) + "px";
}

function send(text) {
  text = (text || "").trim();
  if (!text || busy || !bridge) return;
  addUser(text);
  input.value = "";
  autosize();
  setBusy(true);
  setStatus("thinking…", true);
  startTurn();
  bridge.send(text);
}

$("#composer").addEventListener("submit", (e) => { e.preventDefault(); busy ? stop() : send(input.value); });
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (panel.classList.contains("open")) closePanel(); else stop();
});
input.addEventListener("input", () => { autosize(); updateSend(); });
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(input.value); }
});
document.querySelectorAll(".suggestion").forEach((b) =>
  b.addEventListener("click", () => send(b.dataset.prompt)));
newChatBtn.addEventListener("click", () => {
  if (busy || !bridge) return;
  bridge.newChat();
  thread.innerHTML = "";
  showWelcome();
  input.focus();
});
// Open links in the system browser, not inside the app.
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[href]");
  if (!a) return;
  e.preventDefault();
  if (/^https?:/i.test(a.href) && bridge) bridge.openUrl(a.href);
});

window.focusInput = () => input.focus();

// ── memory panel ──────────────────────────────────────────────
const panel = $("#memory-panel"), backdrop = $("#backdrop"), toast = $("#toast");
const X_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>';
let lastSnapshot = null, freshTexts = new Set(), toastTimer = null, forgetArmed = null;

function openPanel() {
  panel.classList.add("open"); panel.setAttribute("aria-hidden", "false"); backdrop.hidden = false;
  bridge && bridge.getMemory();
}
function closePanel() {
  panel.classList.remove("open"); panel.setAttribute("aria-hidden", "true"); backdrop.hidden = true;
  input.focus();
}
$("#memory-btn").addEventListener("click", openPanel);
$("#memory-close").addEventListener("click", closePanel);
backdrop.addEventListener("click", closePanel);

function removeButton(onClick, label) {
  const b = el("button", "remove", X_ICON);
  b.type = "button"; b.title = label; b.setAttribute("aria-label", label);
  b.addEventListener("click", onClick);
  return b;
}

function renderMemory(snap) {
  lastSnapshot = snap;
  $("#learning-toggle").checked = snap.learning;
  const facts = $("#facts");
  facts.innerHTML = "";
  snap.facts.slice().reverse().forEach((f) => {   // newest first
    const li = el("li");
    if (freshTexts.has(f.text)) li.classList.add("fresh");
    const text = el("span", "text");
    text.textContent = f.text;
    text.title = "Click to edit";
    text.addEventListener("click", () => startEdit(text, f));
    li.append(text, removeButton(() => bridge.deleteFact(f.id), "Forget this"));
    facts.appendChild(li);
  });
  $("#facts-count").textContent = snap.facts.length || "";
  $("#facts-empty").hidden = snap.facts.length > 0;

  const days = $("#days");
  days.innerHTML = "";
  snap.days.slice(0, 14).forEach((d) => {
    const li = el("li");
    const box = el("div", "day");
    const label = el("div", "day-date");
    label.textContent = new Date(d.date + "T12:00").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
    const notes = el("ul", "day-notes");
    d.notes.forEach((n) => { const item = el("li"); item.textContent = n; notes.appendChild(item); });
    box.append(label, notes);
    li.append(box, removeButton(() => bridge.deleteDay(d.date), "Delete this day"));
    days.appendChild(li);
  });
  $("#days-empty").hidden = snap.days.length > 0;
}

function startEdit(node, fact) {
  if (node.isContentEditable) return;
  node.contentEditable = "true";
  node.focus();
  document.getSelection().selectAllChildren(node);
  const finish = (save) => {
    node.contentEditable = "false";
    node.removeEventListener("keydown", onKey);
    node.removeEventListener("blur", onBlur);
    const text = node.textContent.trim();
    if (save && text && text !== fact.text) bridge.editFact(fact.id, text);
    else node.textContent = fact.text;
  };
  const onKey = (e) => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
  };
  const onBlur = () => finish(true);
  node.addEventListener("keydown", onKey);
  node.addEventListener("blur", onBlur);
}

$("#add-fact").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#fact-input").value.trim();
  if (!v || !bridge) return;
  freshTexts = new Set([v]);
  bridge.addFact(v);
  $("#fact-input").value = "";
});
$("#learning-toggle").addEventListener("change", (e) => bridge && bridge.setLearning(e.target.checked));
$("#forget-all").addEventListener("click", (e) => {
  const btn = e.currentTarget;
  if (forgetArmed) {          // second click within 4s confirms
    clearTimeout(forgetArmed); forgetArmed = null;
    btn.textContent = "Forget everything";
    bridge.forgetAll();
    return;
  }
  btn.textContent = "Click again to forget everything";
  forgetArmed = setTimeout(() => { forgetArmed = null; btn.textContent = "Forget everything"; }, 4000);
});

function showToast(changes) {
  if (!changes.length) return;
  freshTexts = new Set(changes.map((c) => c.replace(/^[^:]+:\s*/, "")));
  toast.innerHTML = "";
  const title = el("b"); title.textContent = "Memory updated";
  const detail = el("span"); detail.textContent = changes[0] + (changes.length > 1 ? `  (+${changes.length - 1} more)` : "");
  toast.append(title, detail);
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
}
toast.addEventListener("click", () => { toast.hidden = true; openPanel(); });

// ── wiring to Python ──────────────────────────────────────────
new QWebChannel(qt.webChannelTransport, (channel) => {
  bridge = channel.objects.bridge;

  bridge.init.connect((json) => {
    const cfg = JSON.parse(json);
    document.documentElement.dataset.theme = cfg.theme;
    $("#hl-theme").href = cfg.theme === "light" ? "vendor/hl-light.css" : "vendor/hl-dark.css";
    $("#assistant-name").textContent = cfg.assistant;
    document.querySelectorAll(".assistant-name").forEach((n) => { n.textContent = cfg.assistant; });
    document.title = cfg.assistant;
    input.placeholder = `Message ${cfg.assistant}…`;
    window.USER_NAME = cfg.user;
    if (cfg.error) { addNote(cfg.error, "Fix your .env file and restart.", "error"); input.disabled = true; }
  });
  bridge.history.connect((json) => {
    const items = JSON.parse(json);
    thread.innerHTML = "";
    items.forEach(([role, text]) => (role === "user" ? addUser(text) : addAssistant(text)));
    if (!items.length) showWelcome(); else hideWelcome();
    follow(true);
  });
  bridge.token.connect(onToken);
  bridge.tool.connect(onTool);
  bridge.turnDone.connect(onTurnDone);
  bridge.status.connect((text) => setStatus(text, true));
  bridge.failed.connect((msg) => {
    if (turn && !turn.body.children.length) { turn.row.remove(); turn = null; }
    addNote(msg, null, "error");
  });
  bridge.note.connect((text, sub) => addNote(text, sub));
  bridge.memory.connect((json) => renderMemory(JSON.parse(json)));
  bridge.memorySaved.connect((json) => showToast(JSON.parse(json)));

  bridge.ready();
  input.focus();
});
