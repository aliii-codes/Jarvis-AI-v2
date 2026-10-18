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

function renderMarkdown(target, text, highlight = true) {
  // No <img> from model text: real images arrive as tool results; a model-written link would only be a broken image.
  target.innerHTML = DOMPurify.sanitize(marked.parse(text), { FORBID_TAGS: ["img"] });
  target.querySelectorAll("pre > code").forEach((code) => {
    const pre = code.parentElement;
    const lang = ((code.className || "").match(/language-([\w+#-]+)/) || [])[1] || "";
    if (highlight) {  // skipped while text is still being revealed: re-highlighting every frame is costly
      try {
        if (lang && hljs.getLanguage(lang)) hljs.highlightElement(code);
        else code.innerHTML = hljs.highlightAuto(code.textContent).value;
      } catch (e) { /* plain text is fine */ }
    }
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

// ── generated images ──────────────────────────────────────────
const IMG_ICONS = {
  open: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3h7v7"/><path d="M10 14 21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/></svg>',
  folder: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg>',
};

function imageCard(url, path) {
  const fig = el("figure", "image-card");
  const img = el("img");
  img.alt = "Generated image";
  img.src = url;
  img.addEventListener("load", () => follow());
  img.addEventListener("click", () => openLightbox(url));
  const bar = el("div", "image-actions");
  const mk = (icon, title, fn) => {
    const b = el("button", "", icon); b.type = "button"; b.title = title; b.setAttribute("aria-label", title);
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); });
    return b;
  };
  bar.append(
    mk(ICONS.copy, "Copy image", (b) => { bridge.copyImage(path); b.innerHTML = ICONS.check; setTimeout(() => { b.innerHTML = ICONS.copy; }, 1400); }),
    mk(IMG_ICONS.folder, "Show in folder", () => bridge.showImageInFolder(path)),
    mk(IMG_ICONS.open, "Open in image viewer", () => bridge.openImage(path)),
  );
  fig.append(img, bar);
  return fig;
}

function addImageRow(url, path) {
  hideWelcome();
  const row = el("div", "msg assistant");
  row.appendChild(imageCard(url, path));
  thread.appendChild(row);
}

function onImage(url, path) {
  if (!turn) startTurn();
  settleChips();
  if (turn.skel) { turn.skel.remove(); turn.skel = null; }
  turn.segment = null;  // text after the image starts a new block below it
  turn.body.appendChild(imageCard(url, path));
  follow();
}

const lightbox = el("div", "lightbox");
lightbox.hidden = true;
lightbox.appendChild(el("img"));
document.body.appendChild(lightbox);
lightbox.addEventListener("click", () => { lightbox.hidden = true; });
function openLightbox(url) { lightbox.querySelector("img").src = url; lightbox.hidden = false; }

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
  turn = { row, body, typing, segment: null, chips: [], texts: [], ticking: false, done: false, stopped: false };
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

// Smooth streaming. Groq delivers a whole reply in well under a second, which reads as "nothing, then
// everything". Incoming text is buffered and revealed at a steady pace: faster when a lot is waiting,
// never slower than ~180 chars/s, so a typical reply takes 2-3 seconds to type out.
function onToken(text) {
  if (!turn) startTurn();
  turn.typing.hidden = true;
  if (!turn.segment) {
    settleChips();
    turn.segment = { node: el("div", "content"), text: "", shown: 0 };
    turn.body.appendChild(turn.segment.node);
    turn.texts.push(turn.segment);
  }
  turn.segment.text += text;
  setStatus("typing…", true);
  startTicking();
}

function startTicking() {
  if (turn && !turn.ticking) { turn.ticking = true; requestAnimationFrame(tick); }
}

function withCaret(node) {
  // Follow the last *node* (text or element) so the caret lands after trailing plain text,
  // not after the last bold/link element that happens to precede it.
  // Whitespace-only text nodes (Markdown emits "\n" between blocks) don't count as content.
  const lastReal = (n) => {
    let c = n.lastChild;
    while (c && c.nodeType === Node.TEXT_NODE && !c.textContent.trim()) c = c.previousSibling;
    return c;
  };
  let last = node, c;
  while ((c = lastReal(last)) && c.nodeType === Node.ELEMENT_NODE && !/^(TABLE|HR|BR)$/.test(c.tagName)) last = c;
  if (c && c.nodeType === Node.TEXT_NODE) c.after(el("span", "caret"));
  else last.appendChild(el("span", "caret"));
}

function tick() {
  if (!turn) return;
  const seg = turn.texts.find((s) => s.shown < s.text.length);  // reveal segments in order
  if (seg) {
    const backlog = seg.text.length - seg.shown;
    seg.shown = Math.min(seg.text.length, seg.shown + Math.min(40, Math.max(3, Math.ceil(backlog / 90))));
    renderMarkdown(seg.node, seg.text.slice(0, seg.shown), false);
    withCaret(seg.node);
    follow();
    requestAnimationFrame(tick);
    return;
  }
  turn.ticking = false;
  if (turn.done) finishTurn();  // everything received and revealed
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
  if (name === "generate_image" && !turn.skel) {  // placeholder until the picture arrives
    turn.skel = el("div", "image-skel", "<span>Creating image…</span>");
    turn.body.appendChild(turn.skel);
  }
  turn.typing.hidden = true;
  setStatus(running.toLowerCase(), true);
  follow();
}

function onTurnDone(stopped) {
  if (!turn) { setBusy(false); return; }
  turn.done = true;
  turn.stopped = stopped;
  if (stopped) turn.texts.forEach((s) => { s.shown = s.text.length; });  // Stop: show what arrived, now
  if (turn.ticking) return;  // tick() calls finishTurn once the reveal catches up
  finishTurn();
}

function finishTurn() {
  settleChips();
  if (turn.skel) { turn.skel.remove(); turn.skel = null; }
  if (turn.stopped) turn.body.appendChild(el("div", "stopped", "Stopped"));
  turn.texts.forEach((s) => renderMarkdown(s.node, s.text));  // final render, with code highlighting
  turn.typing.remove();
  const full = turn.texts.map((s) => s.text).join("\n\n").trim();
  if (full) turn.row.appendChild(actionsFor(() => full));
  if (!turn.body.children.length) turn.row.remove();
  turn = null;
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
  if (!lightbox.hidden) lightbox.hidden = true;
  else if (document.querySelector(".drawer.open")) closeDrawers();
  else stop();
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

// ── tasks & notes panel ───────────────────────────────────────
const listsPanel = $("#lists-panel"), badge = $("#lists-badge");
let listsSnap = { tasks: [], notes: [], attention: 0 }, listEditing = false, listsPending = null;

function switchTab(name) {
  listsPanel.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $("#tab-tasks").hidden = name !== "tasks";
  $("#tab-notes").hidden = name !== "notes";
  (name === "tasks" ? $("#task-input") : $("#note-input")).focus();
}
listsPanel.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
listsPanel.querySelector(".drawer-close").addEventListener("click", closeDrawers);
$("#lists-btn").addEventListener("click", () => { openDrawer(listsPanel); bridge && bridge.getLists(); setTimeout(() => $("#task-input").focus(), 50); });

// Inline editing shared by tasks and notes. Notes are multi-line: Ctrl+Enter or clicking away saves.
function inlineEdit(node, original, onSave, multiline) {
  if (node.isContentEditable) return;
  listEditing = true;
  node.contentEditable = "true"; node.focus();
  document.getSelection().selectAllChildren(node);
  const finish = (save) => {
    node.contentEditable = "false";
    node.removeEventListener("keydown", onKey); node.removeEventListener("blur", onBlur);
    const v = (multiline ? node.innerText : node.textContent).trim();
    listEditing = false;
    if (save && v && v !== original) onSave(v); else node.textContent = original;
    if (listsPending) { const snap = listsPending; listsPending = null; renderLists(snap); }
  };
  const onKey = (e) => {
    if (e.key === "Enter" && (!multiline || e.ctrlKey)) { e.preventDefault(); finish(true); }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
  };
  const onBlur = () => finish(true);
  node.addEventListener("keydown", onKey); node.addEventListener("blur", onBlur);
}

function taskItem(t) {
  const li = el("li", t.done ? "done" : "");
  const check = el("button", "check" + (t.done ? " on" : ""), ICONS.check);
  check.type = "button"; check.title = t.done ? "Mark as not done" : "Mark as done";
  check.addEventListener("click", () => bridge.setTaskDone(t.id, !t.done));
  const text = el("span", "text"); text.textContent = t.text; text.title = "Click to edit";
  text.addEventListener("click", () => inlineEdit(text, t.text, (v) => bridge.editTask(t.id, v), false));
  li.append(check, text);
  if (t.due_label && !t.done) {
    const due = el("span", "due" + (t.overdue ? " overdue" : t.due_label.startsWith("today") ? " today" : ""));
    due.textContent = t.overdue ? `overdue · ${t.due_label}` : t.due_label;
    li.appendChild(due);
  }
  li.appendChild(removeButton(() => bridge.deleteTask(t.id), "Delete task"));
  return li;
}

function noteItem(n) {
  const li = el("li");
  const body = el("div", "note-body");
  const text = el("div", "text"); text.textContent = n.text; text.title = "Click to edit (Ctrl+Enter saves)";
  text.addEventListener("click", () => inlineEdit(text, n.text, (v) => bridge.editNote(n.id, v), true));
  const meta = el("div", "note-meta");
  meta.textContent = new Date(n.created).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  body.append(text, meta);
  li.append(body, removeButton(() => bridge.deleteNote(n.id), "Delete note"));
  return li;
}

function renderNotes() {
  const q = $("#note-search").value.trim().toLowerCase();
  const shown = listsSnap.notes.filter((n) => !q || n.text.toLowerCase().includes(q));
  const list = $("#note-list");
  list.innerHTML = "";
  shown.forEach((n) => list.appendChild(noteItem(n)));
  $("#notes-empty").hidden = shown.length > 0;
  $("#notes-empty").textContent = q ? "No notes match." : "No notes yet. Try “note: the café wifi is …”";
}

function renderLists(snap) {
  if (listEditing) { listsPending = snap; return; }  // don't clobber an edit in progress
  listsSnap = snap;
  badge.hidden = !snap.attention;
  badge.textContent = snap.attention > 9 ? "9+" : snap.attention;
  $("#lists-btn").title = snap.attention ? `Tasks & notes (${snap.attention} due)` : "Tasks & notes";

  const open = snap.tasks.filter((t) => !t.done), done = snap.tasks.filter((t) => t.done);
  const list = $("#task-list");
  list.innerHTML = "";
  open.forEach((t) => list.appendChild(taskItem(t)));
  $("#tasks-empty").hidden = open.length > 0;
  const doneList = $("#done-list");
  doneList.innerHTML = "";
  done.forEach((t) => doneList.appendChild(taskItem(t)));
  $("#done-wrap").hidden = !done.length;
  $("#done-count").textContent = done.length || "";
  renderNotes();
}

$("#add-task").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#task-input").value.trim();
  if (!text || !bridge) return;
  bridge.addTask(text, $("#task-due").value || "");
  $("#task-input").value = ""; $("#task-due").value = "";
});
$("#add-note").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#note-input").value.trim();
  if (!text || !bridge) return;
  bridge.addNote(text);
  $("#note-input").value = "";
});
$("#note-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); $("#add-note").requestSubmit(); }
});
$("#note-search").addEventListener("input", renderNotes);

// ── chat history sidebar ──────────────────────────────────────
const app = $("#app"), chatList = $("#chat-list"), chatSearch = $("#chat-search");
const PENCIL = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
const TRASH = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>';
let chats = { threads: [], current: null }, searchTimer = null, searching = false;

function storeGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function storeSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode etc. */ } }

function setSidebar(open, remember) {
  app.classList.toggle("side-closed", !open);
  if (remember) storeSet("sidebar", open ? "open" : "closed");
}
const savedSidebar = storeGet("sidebar");
setSidebar(savedSidebar ? savedSidebar === "open" : window.innerWidth >= 1000, false);
$("#side-toggle").addEventListener("click", () => setSidebar(app.classList.contains("side-closed"), true));
$("#side-scrim").addEventListener("click", () => setSidebar(false, false));
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") { e.preventDefault(); $("#side-toggle").click(); }
});
const narrow = () => window.innerWidth <= 760;

function groupLabel(iso) {
  const d = new Date(iso), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return "Previous 7 days";
  if (diff < 30) return "Previous 30 days";
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function chatItem(t, snippet) {
  const item = el("div", "chat-item" + (t.id === chats.current ? " active" : ""));
  item.dataset.id = t.id;
  const text = el("span", "chat-text");
  const title = el("span", "chat-title"); title.textContent = t.title || "Untitled chat";
  text.appendChild(title);
  if (snippet) { const sn = el("span", "chat-snippet"); sn.textContent = snippet; text.appendChild(sn); }
  const actions = el("span", "chat-actions");
  const ren = el("button", "", PENCIL); ren.title = "Rename"; ren.type = "button";
  const del = el("button", "del", TRASH); del.title = "Delete"; del.type = "button";
  actions.append(ren, del);
  item.append(text, actions);

  item.addEventListener("click", (e) => {
    if (e.target.closest(".chat-actions") || title.isContentEditable || item.classList.contains("confirming")) return;
    if (busy || !bridge) return;
    bridge.openThread(t.id);
    if (narrow()) setSidebar(false, false);
  });
  ren.addEventListener("click", (e) => { e.stopPropagation(); renameChat(title, t); });
  del.addEventListener("click", (e) => { e.stopPropagation(); confirmDelete(item, t); });
  return item;
}

function renameChat(title, t) {
  title.contentEditable = "true"; title.focus();
  document.getSelection().selectAllChildren(title);
  const finish = (save) => {
    title.contentEditable = "false";
    title.removeEventListener("keydown", onKey); title.removeEventListener("blur", onBlur);
    const v = title.textContent.trim();
    if (save && v && v !== t.title) bridge.renameThread(t.id, v); else title.textContent = t.title;
  };
  const onKey = (e) => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
  };
  const onBlur = () => finish(true);
  title.addEventListener("keydown", onKey); title.addEventListener("blur", onBlur);
}

function confirmDelete(item, t) {
  if (busy && t.id === chats.current) return;
  item.classList.add("confirming");
  item.innerHTML = "";
  const q = el("span", "confirm-text"); q.textContent = "Delete this chat?";
  const actions = el("span", "chat-actions");
  const yes = el("button", "confirm-yes", "Delete"); yes.type = "button";
  const no = el("button", "", '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>');
  no.type = "button"; no.title = "Cancel";
  actions.append(yes, no);
  item.append(q, actions);
  yes.addEventListener("click", (e) => { e.stopPropagation(); bridge.deleteThread(t.id); });
  no.addEventListener("click", (e) => { e.stopPropagation(); renderChats(); });
}

function renderChats() {
  if (searching) return;
  chatList.innerHTML = "";
  if (!chats.threads.length) { chatList.appendChild(el("div", "chat-empty", "Your chats will show up here.")); return; }
  let last = null;
  chats.threads.forEach((t) => {
    const g = groupLabel(t.updated);
    if (g !== last) { const h = el("div", "chat-group"); h.textContent = g; chatList.appendChild(h); last = g; }
    chatList.appendChild(chatItem(t));
  });
}

function renderSearch(results) {
  chatList.innerHTML = "";
  if (!results.length) { chatList.appendChild(el("div", "chat-empty", "No chats match.")); return; }
  const h = el("div", "chat-group"); h.textContent = `${results.length} result${results.length > 1 ? "s" : ""}`;
  chatList.appendChild(h);
  results.forEach((r) => chatList.appendChild(chatItem(r, r.snippet)));
}

chatSearch.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = chatSearch.value.trim();
  if (!q) { searching = false; renderChats(); return; }
  searchTimer = setTimeout(() => { searching = true; bridge && bridge.searchChats(q); }, 220);
});
chatSearch.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { e.stopPropagation(); chatSearch.value = ""; searching = false; renderChats(); input.focus(); }
});
$("#side-new").addEventListener("click", () => { newChatBtn.click(); if (narrow()) setSidebar(false, false); });

// ── memory panel ──────────────────────────────────────────────
const panel = $("#memory-panel"), backdrop = $("#backdrop"), toast = $("#toast");
const X_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>';
let lastSnapshot = null, freshTexts = new Set(), toastTimer = null, forgetArmed = null;

function hideDrawers() {
  document.querySelectorAll(".drawer.open").forEach((d) => { d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); });
}
function openDrawer(d) {
  hideDrawers();
  d.classList.add("open"); d.setAttribute("aria-hidden", "false"); backdrop.hidden = false;
}
function closeDrawers() { hideDrawers(); backdrop.hidden = true; input.focus(); }
function openPanel() { openDrawer(panel); bridge && bridge.getMemory(); }
$("#memory-btn").addEventListener("click", openPanel);
$("#memory-close").addEventListener("click", closeDrawers);
backdrop.addEventListener("click", closeDrawers);

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
    items.forEach(([role, text, path]) =>
      role === "user" ? addUser(text) : role === "image" ? addImageRow(text, path) : addAssistant(text));
    if (!items.length) showWelcome(); else hideWelcome();
    follow(true);
  });
  bridge.token.connect(onToken);
  bridge.tool.connect(onTool);
  bridge.image.connect(onImage);
  bridge.turnDone.connect(onTurnDone);
  bridge.status.connect((text) => setStatus(text, true));
  bridge.failed.connect((msg) => {
    if (turn && !turn.body.children.length) { turn.row.remove(); turn = null; }
    addNote(msg, null, "error");
  });
  bridge.note.connect((text, sub) => addNote(text, sub));
  bridge.memory.connect((json) => renderMemory(JSON.parse(json)));
  bridge.threads.connect((json) => { chats = JSON.parse(json); renderChats(); });
  bridge.lists.connect((json) => renderLists(JSON.parse(json)));
  bridge.searchResults.connect((json) => { if (searching) renderSearch(JSON.parse(json)); });
  bridge.memorySaved.connect((json) => showToast(JSON.parse(json)));

  bridge.ready();
  input.focus();
});
