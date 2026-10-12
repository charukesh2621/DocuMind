import { API_BASE, fetchJson } from './api.js';
import { openEvidenceModal } from './evidence.js';

/* ---------------- State ---------------- */

let chats = loadChats();
let currentChatId = chats.length ? chats[0].id : null;
let availableDocuments = [];

/* ---------------- Chat State ---------------- */

export function loadChats() {
  try {
    const raw = localStorage.getItem("documind_chats_v2");
    if (raw) return JSON.parse(raw);
  } catch (e) {}
  return [];
}

export function saveChats() {
  try {
    localStorage.setItem("documind_chats_v2", JSON.stringify(chats));
  } catch (e) {}
}

export function getCurrentChat() {
  return chats.find(c => c.id === currentChatId) || null;
}

export function setCurrentChatId(id) {
  currentChatId = id;
}

export function getChats() {
  return chats;
}

export function setChats(newChats) {
  chats = newChats;
}

/* ---------------- Helpers ---------------- */

function ensureCurrentChat() {
  let chat = getCurrentChat();

  if (!chat) {
    chat = {
      id: crypto.randomUUID(),
      title: "New chat",
      conversation_id: crypto.randomUUID(),
      filenames: [],
      messages: []
    };

    chats.unshift(chat);
    currentChatId = chat.id;
    saveChats();
  }

  if (!chat.messages) chat.messages = [];
  if (!chat.filenames) chat.filenames = [];
  if (!chat.conversation_id) chat.conversation_id = chat.id;

  return chat;
}

/* ---------------- Source filename cleanup ---------------- */

// The backend saves uploads as "{uuid4().hex}_{original_filename}" (see /upload
// in backend/main.py) to avoid collisions. Strip that exact 32-char hex prefix
// so only the original PDF/DOCX/etc. filename is ever shown to the user.
export function cleanSourceFilename(filename) {
  if (!filename) return "";
  return String(filename).replace(/^[0-9a-fA-F]{32}_/, "");
}

// The model is instructed to cite sources as "[filename.ext, Page: N]", but it
// sometimes also emits non-citation commentary in brackets (e.g. "[No specific
// page number citation is necessary...]"). Strip any bracketed text that is not
// a real citation, leaving genuine [filename, Page: N] citations untouched.
function stripNonCitationNotes(text) {
  return String(text || "")
    .replace(/\[([^\[\]]+)\]/g, (match, inner) => {
      const isCitation = /\.[a-z0-9]{2,5}\s*,\s*page\s*:?\s*\d+/i.test(inner);
      return isCitation ? match : "";
    })
    .replace(/[ \t]{2,}/g, " ")
    .replace(/ +\n/g, "\n")
    .trim();
}

/* ---------------- Markdown ---------------- */

export function renderMarkdownLite(text) {
  const escapeHtml = (s) => String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  const inlineFormat = (s) =>
    escapeHtml(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  const lines = stripNonCitationNotes(text).replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let paraBuffer = [];
  let listBuffer = [];

  function flushParagraph() {
    if (!paraBuffer.length) return;
    html += "<p>" + inlineFormat(paraBuffer.join(" ")) + "</p>";
    paraBuffer = [];
  }

  function flushList() {
    if (!listBuffer.length) return;
    html += "<ul>" +
      listBuffer.map(item => "<li>" + inlineFormat(item) + "</li>").join("") +
      "</ul>";
    listBuffer = [];
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();

    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }

    const bulletMatch = line.match(/^[-*]\s+(.*)$/);

    if (bulletMatch) {
      flushParagraph();
      listBuffer.push(bulletMatch[1]);
      continue;
    }

    const headingMatch = line.match(/^\*\*(.+)\*\*:?$/);

    if (headingMatch && !paraBuffer.length) {
      flushList();
      html += "<h4>" + escapeHtml(headingMatch[1]) + "</h4>";
      continue;
    }

    flushList();
    paraBuffer.push(line);
  }

  flushParagraph();
  flushList();

  return html || ("<p>" + inlineFormat(String(text || "")) + "</p>");
}

/* ---------------- Message Rendering ---------------- */

export function renderMessageRow(m) {
  const row = document.createElement("div");
  row.className = "msg-row " + m.role;

  const roleLabel = document.createElement("div");
  roleLabel.className = "msg-role";
  roleLabel.textContent = m.role === "user" ? "You" : "DocuMind";
  row.appendChild(roleLabel);

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";

  if (m.role === "assistant") {
    bubble.innerHTML = renderMarkdownLite(m.text);
  } else {
    bubble.textContent = m.text;
  }

  row.appendChild(bubble);

  if (m.sources && m.sources.length) {
    const src = document.createElement("div");
    src.className = "msg-sources";

    const seenNames = new Set();

    m.sources.forEach(s => {
      const cleanName = cleanSourceFilename(s.filename);
      if (!cleanName || seenNames.has(cleanName)) return;
      seenNames.add(cleanName);

      const chip = document.createElement("span");
      chip.className = "source-chip";
      chip.textContent = cleanName;

      chip.addEventListener("click", () => openEvidenceModal(s));
      src.appendChild(chip);
    });

    if (seenNames.size) row.appendChild(src);
  }

  if (m.possibleConflict) {
    const conflict = document.createElement("div");
    conflict.className = "msg-conflict";
    conflict.textContent =
      "? Multiple sources � details may vary across documents";
    row.appendChild(conflict);
  }

  return row;
}

/* ---------------- Rendering ---------------- */

export function renderTopbar() {
  const chat = ensureCurrentChat();

  const title = document.getElementById("chatTitle");
  const meta = document.getElementById("chatMeta");

  title.textContent = chat.title || "New chat";

  const count = chat.filenames ? chat.filenames.length : 0;
  meta.textContent = `${count} document${count === 1 ? "" : "s"}`;
}

export function renderDocChips() {
  const chat = ensureCurrentChat();
  const bar = document.getElementById("docChipBar");

  bar.innerHTML = "";

  for (const filename of chat.filenames || []) {
    const chip = document.createElement("span");
    chip.className = "doc-chip";
    chip.textContent = filename;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "�";

    remove.addEventListener("click", () => {
      chat.filenames = chat.filenames.filter(f => f !== filename);
      saveChats();
      renderAll();
    });

    chip.appendChild(remove);
    bar.appendChild(chip);
  }
}

export function renderMessages() {
  const chat = ensureCurrentChat();
  const container = document.getElementById("messagesInner");

  container.innerHTML = "";

  if (!chat.messages || !chat.messages.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Ask a question about your documents to get started.";
    container.appendChild(empty);
    return;
  }

  for (const message of chat.messages) {
    container.appendChild(renderMessageRow(message));
  }

  container.parentElement.scrollTop = container.parentElement.scrollHeight;
}

export function renderHistory() {
  const list = document.getElementById("historyList");
  list.innerHTML = "";

  for (const chat of chats) {
    const item = document.createElement("div");
    item.className = "history-item" +
      (chat.id === currentChatId ? " active" : "");

    item.addEventListener("click", () => {
      currentChatId = chat.id;
      renderAll();
    });

    const titleSpan = document.createElement("span");
    titleSpan.className = "history-title";
    titleSpan.textContent = chat.title || "New chat";
    item.appendChild(titleSpan);

    const menuBtn = document.createElement("button");
    menuBtn.type = "button";
    menuBtn.className = "history-menu-btn";
    menuBtn.textContent = "⋯";
    menuBtn.title = "Chat options";
    item.appendChild(menuBtn);

    const menu = document.createElement("div");
    menu.className = "history-menu";
    menu.hidden = true;

    const renameBtn = document.createElement("button");
    renameBtn.type = "button";
    renameBtn.className = "history-menu-option";
    renameBtn.textContent = "Rename";
    menu.appendChild(renameBtn);

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "history-menu-option delete";
    deleteBtn.textContent = "Delete";
    menu.appendChild(deleteBtn);

    item.appendChild(menu);

    menuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const isOpen = !menu.hidden;
      closeAllHistoryMenus();
      if (!isOpen) {
        menu.hidden = false;
        item.classList.add("menu-open");
      }
    });

    renameBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeAllHistoryMenus();
      startRenameChat(chat.id, titleSpan);
    });

    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeAllHistoryMenus();
      deleteChat(chat.id);
    });

    list.appendChild(item);
  }
}

function closeAllHistoryMenus() {
  document.querySelectorAll(".history-menu").forEach(m => { m.hidden = true; });
  document.querySelectorAll(".history-item.menu-open").forEach(i => i.classList.remove("menu-open"));
}

// Inline-rename: swap the title span for a text input in place (no full
// re-render), matching the title to the existing localStorage chat state.
function startRenameChat(chatId, titleSpanEl) {
  const chat = chats.find(c => c.id === chatId);
  if (!chat) return;

  const input = document.createElement("input");
  input.type = "text";
  input.className = "history-title-input";
  input.value = chat.title || "";

  titleSpanEl.replaceWith(input);
  input.focus();
  input.select();

  let committed = false;

  function commit() {
    if (committed) return;
    committed = true;

    const val = input.value.trim();
    if (val) chat.title = val;

    saveChats();
    renderAll();
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
    }
    if (e.key === "Escape") {
      committed = true;
      renderAll();
    }
  });
  input.addEventListener("blur", commit);
  input.addEventListener("click", (e) => e.stopPropagation());
}

// Permanently removes a chat from the existing localStorage chat history.
// If the deleted chat is currently open, switches to another existing chat,
// or creates a new one if none remain.
function deleteChat(chatId) {
  const chat = chats.find(c => c.id === chatId);
  if (!chat) return;

  const confirmed = window.confirm(
    `Delete "${chat.title || "New chat"}"?\n\nThis will permanently delete this chat and its conversation history. This action cannot be undone.`
  );
  if (!confirmed) return;

  chats = chats.filter(c => c.id !== chatId);

  if (currentChatId === chatId) {
    currentChatId = chats.length ? chats[0].id : null;
  }

  saveChats();
  renderAll();
}

/* ---------------- Documents ---------------- */

export async function refreshDocuments() {
  try {
    const data = await fetchJson("/documents");
    availableDocuments = data.documents || [];

    const chat = ensureCurrentChat();

    const existing = new Set(availableDocuments.map(d => d.filename));

    chat.filenames = (chat.filenames || []).filter(f => existing.has(f));

    saveChats();
    renderAll();

    return availableDocuments;
  } catch (error) {
    console.error("Failed to load documents:", error);
    return [];
  }
}

export function addDocumentToCurrentChat(filename) {
  const chat = ensureCurrentChat();

  if (!chat.filenames.includes(filename)) {
    chat.filenames.push(filename);
    saveChats();
  }

  renderAll();
}

/* ---------------- Chat / Ask ---------------- */

async function submitQuestion(query) {
  const chat = ensureCurrentChat();

  const userMessage = {
    role: "user",
    text: query
  };

  chat.messages.push(userMessage);
  saveChats();
  renderAll();

  const loading = {
    role: "assistant",
    text: "Thinking..."
  };

  chat.messages.push(loading);
  renderMessages();

  try {
    const response = await fetchJson("/ask", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        query,
        top_k: 3,
        conversation_id: chat.conversation_id,
        filenames: chat.filenames.length ? chat.filenames : null
      })
    });

    chat.messages.pop();

    chat.messages.push({
      role: "assistant",
      text: response.answer || "No answer returned.",
      sources: response.sources || [],
      possibleConflict: response.possible_conflict || false
    });

    if (chat.title === "New chat") {
      chat.title = query.length > 45
        ? query.slice(0, 45) + "�"
        : query;
    }

    saveChats();
    renderAll();

  } catch (error) {
    chat.messages.pop();

    chat.messages.push({
      role: "assistant",
      text: `Error: ${error.message}`
    });

    saveChats();
    renderAll();
  }
}

/* ---------------- New Chat ---------------- */

function createNewChat() {
  const chat = {
    id: crypto.randomUUID(),
    title: "New chat",
    conversation_id: crypto.randomUUID(),
    filenames: [],
    messages: []
  };

  chats.unshift(chat);
  currentChatId = chat.id;

  saveChats();
  renderAll();
}

/* ---------------- Initialization ---------------- */

export function initChat() {
  ensureCurrentChat();

  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const newChatBtn = document.getElementById("newChatBtn");

  // Close any open chat-options (⋯) menu when clicking anywhere outside it.
  document.addEventListener("click", () => closeAllHistoryMenus());

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const query = input.value.trim();

    if (!query) return;

    input.value = "";
    await submitQuestion(query);
  });

  newChatBtn.addEventListener("click", createNewChat);
}

export function renderAll() {
  ensureCurrentChat();
  renderHistory();
  renderTopbar();
  renderDocChips();
  renderMessages();
}
