const API_BASE = "http://localhost:8000";
const STORAGE_KEY = "answerbot_chat_sessions";

// ---------- DOM refs ----------
const fileInput       = document.getElementById("file-input");
const fileQueue       = document.getElementById("file-queue");
const uploadBtn       = document.getElementById("upload-btn");
const uploadStatus    = document.getElementById("upload-status");
const libraryList     = document.getElementById("library-list");
const libraryCount    = document.getElementById("library-count");

const chatMessages    = document.getElementById("chat-messages");
const chatEmpty       = document.getElementById("chat-empty");
const queryInput      = document.getElementById("query-input");
const askBtn          = document.getElementById("ask-btn");
const askLoader       = document.getElementById("ask-loader");
const sendIcon        = document.getElementById("send-icon");

const newChatBtn      = document.getElementById("new-chat-btn");
const sidebarChatList = document.getElementById("sidebar-chat-list");
const micBtn          = document.getElementById("mic-btn");

const confirmModal    = document.getElementById("confirm-modal");
const modalTitle      = document.getElementById("modal-title");
const modalMessage    = document.getElementById("modal-message");
const modalCancel     = document.getElementById("modal-cancel");
const modalConfirm    = document.getElementById("modal-confirm");

const progressContainer = document.getElementById("query-progress-container");
const progressBar       = document.getElementById("progress-bar");
const progressStage     = document.getElementById("progress-stage");
const progressPercent   = document.getElementById("progress-percent");

// ---------- State ----------
let stagedFiles        = [];
let pendingDeleteId    = null;
let pendingDeleteType  = null; // 'document' or 'chat'
let isQuerying         = false;
let isListening        = false;
let mediaRecorder      = null;
let audioChunks        = [];

let chatSessions = {};
let currentChatId = null;

function generateId() { return Math.random().toString(36).substring(2, 9); }

// ---------- Chat history (persisted in localStorage) ----------
function loadSessions() {
    try {
        const data = localStorage.getItem(STORAGE_KEY);
        if (data) chatSessions = JSON.parse(data);
    } catch { chatSessions = {}; }
}

function saveSessions() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(chatSessions)); } catch {}
}

// ---------- Init ----------
document.addEventListener("DOMContentLoaded", () => {
    fetchLibrary();
    loadSessions();
    const sessionIds = Object.keys(chatSessions);
    if (sessionIds.length > 0) {
        // Sort by updatedAt descending
        sessionIds.sort((a, b) => chatSessions[b].updatedAt - chatSessions[a].updatedAt);
        currentChatId = sessionIds[0];
    } else {
        createNewChat();
    }
    renderSidebar();
    loadCurrentChat();

    queryInput.addEventListener("keydown", e => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuery(); }
    });

    initSpeech();
    micBtn.addEventListener("click", toggleMic);
});

newChatBtn.addEventListener("click", createNewChat);

function createNewChat() {
    currentChatId = generateId();
    chatSessions[currentChatId] = {
        title: "New Chat",
        updatedAt: Date.now(),
        messages: []
    };
    saveSessions();
    renderSidebar();
    loadCurrentChat();
}

function deleteChat(id, e) {
    e.stopPropagation();
    const session = chatSessions[id];
    const displayName = session ? (session.title || "Untitled Chat") : "this chat";
    showDeleteModal("chat", id, displayName);
}

function executeChatDelete(id) {
    delete chatSessions[id];
    saveSessions();
    
    // If we deleted the active chat, pick another or make new
    if (currentChatId === id) {
        const remaining = Object.keys(chatSessions);
        if (remaining.length > 0) {
            remaining.sort((a, b) => chatSessions[b].updatedAt - chatSessions[a].updatedAt);
            currentChatId = remaining[0];
        } else {
            createNewChat();
            return;
        }
    }
    renderSidebar();
    loadCurrentChat();
}

function selectChat(id) {
    if (isQuerying) return;
    currentChatId = id;
    renderSidebar();
    loadCurrentChat();
}

function renderSidebar() {
    sidebarChatList.innerHTML = "";
    const sessionIds = Object.keys(chatSessions);
    sessionIds.sort((a, b) => chatSessions[b].updatedAt - chatSessions[a].updatedAt);

    sessionIds.forEach(id => {
        const session = chatSessions[id];
        const item = document.createElement("div");
        item.className = `sidebar-chat-item ${id === currentChatId ? 'active' : ''}`;
        item.onclick = () => selectChat(id);

        const titleSpan = document.createElement("span");
        titleSpan.className = "sidebar-chat-title";
        titleSpan.textContent = session.title;

        const delBtn = document.createElement("button");
        delBtn.className = "chat-delete-btn";
        delBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18m-2 0v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6m3 0V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>`;
        delBtn.onclick = (e) => deleteChat(id, e);

        item.appendChild(titleSpan);
        item.appendChild(delBtn);
        sidebarChatList.appendChild(item);
    });
}

function loadCurrentChat() {
    chatMessages.innerHTML = "";
    const session = chatSessions[currentChatId];
    if (!session || session.messages.length === 0) {
        chatMessages.appendChild(rebuildEmptyState());
        return;
    }
    session.messages.forEach(entry => renderMessage(entry, false));
    scrollToBottom();
}

function rebuildEmptyState() {
    const el = document.createElement("div");
    el.className = "chat-empty-state";
    el.id = "chat-empty";
    el.innerHTML = `
        <div class="chat-empty-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
        </div>
        <p>Ask anything about your uploaded documents.</p>
        <span>Your conversation history is saved automatically.</span>
    `;
    return el;
}

// ---------- Voice Input (Whisper Migration) ----------
function initSpeech() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.warn("MediaDevices API not supported. Hiding mic.");
        micBtn.style.display = "none";
        return;
    }
}

async function toggleMic() {
    if (isListening) {
        await stopMic();
    } else {
        await startMic();
    }
}

async function startMic() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];

        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            await processLiveTranscription(audioBlob);
            
            // Cleanup stream
            stream.getTracks().forEach(track => track.stop());
        };

        mediaRecorder.start();
        isListening = true;
        micBtn.classList.add("mic-active");
        queryInput.placeholder = "Listening... (Click mic to stop)";
    } catch (err) {
        console.error("Error accessing microphone:", err);
        alert("Could not access microphone. Please check permissions.");
    }
}

async function stopMic() {
    if (!mediaRecorder || isListening === false) return;
    isListening = false;
    mediaRecorder.stop();
    micBtn.classList.remove("mic-active");
    queryInput.placeholder = "Transcribing voice...";
}

async function processLiveTranscription(blob) {
    const formData = new FormData();
    formData.append("audio", blob, "recording.webm");

    try {
        const response = await fetch(`${API_BASE}/transcribe-live`, {
            method: "POST",
            body: formData
        });
        
        if (!response.ok) throw new Error("Transcription failed");
        
        const data = await response.json();
        if (data.text) {
            queryInput.value = data.text;
            // Optionally auto-send query
            // sendQuery(); 
        }
    } catch (err) {
        console.error("Transcription error:", err);
    } finally {
        queryInput.placeholder = "Ask anything about your documents...";
    }
}

// ---------- Send query ----------
askBtn.addEventListener("click", sendQuery);

async function sendQuery() {
    const query = queryInput.value.trim();
    if (!query || isQuerying) return;

    isQuerying = true;
    setLoading(true);

    // Hide empty state
    const emptyEl = document.getElementById("chat-empty");
    if (emptyEl) emptyEl.style.display = "none";

    // Add user bubble immediately
    const userEntry = { role: "user", text: query, ts: Date.now() };
    appendToHistory(userEntry);
    renderMessage(userEntry, true);
    queryInput.value = "";

    // Show typing indicator
    const typingEl = addTypingIndicator();

    // Progress simulation
    let queryActive = true;
    updateProgress(10, "Initializing context search...");
    const t1 = setTimeout(() => { if (queryActive) updateProgress(40, "Retrieving relevant documents..."); }, 700);
    const t2 = setTimeout(() => { if (queryActive) updateProgress(75, "Synthesizing answer..."); }, 1900);

    try {
        const formData = new FormData();
        formData.append("query", query);
        
        // Pass stripped context history
        const sessionHistory = chatSessions[currentChatId].messages.map(m => ({
            role: m.role,
            content: m.text
        }));
        formData.append("chat_history", JSON.stringify(sessionHistory));

        const response = await fetch(`${API_BASE}/query`, { method: "POST", body: formData });
        queryActive = false;
        clearTimeout(t1); clearTimeout(t2);
        updateProgress(100, "Finalizing...");

        if (!response.ok) throw new Error("Server error. Check API config or server logs.");

        const data = await response.json();

        await delay(500);
        progressContainer.style.display = "none";
        typingEl.remove();

        const botEntry = {
            role: "bot",
            text: data.answer,
            images: data.images || [],
            sources: data.sources || [],
            chunks: data.retrieved_results || [],
            ts: Date.now()
        };
        appendToHistory(botEntry);
        renderMessage(botEntry, true);

    } catch (err) {
        queryActive = false;
        clearTimeout(t1); clearTimeout(t2);
        progressContainer.style.display = "none";
        typingEl.remove();

        const errEntry = { role: "bot", text: `⚠️ ${err.message}`, ts: Date.now() };
        appendToHistory(errEntry);
        renderMessage(errEntry, true);
    } finally {
        isQuerying = false;
        setLoading(false);
        scrollToBottom();
    }
}

// ---------- Render a single message ----------
function renderMessage(entry, animate) {
    const wrapper = document.createElement("div");
    wrapper.className = `chat-message ${entry.role}`;
    if (!animate) wrapper.style.animation = "none";

    // Bubble
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.textContent = entry.text;
    wrapper.appendChild(bubble);

    // Timestamp
    const ts = document.createElement("span");
    ts.className = "chat-ts";
    ts.textContent = formatTime(entry.ts);
    wrapper.appendChild(ts);

    // Images (bot only)
    if (entry.role === "bot" && entry.images && entry.images.length > 0) {
        const imagesContainer = document.createElement("div");
        imagesContainer.className = "chat-images-container";
        entry.images.forEach(imgPath => {
            const wrap = document.createElement("div");
            wrap.className = "chat-img-wrapper";
            
            const img = document.createElement("img");
            img.src = imgPath.startsWith("http") ? imgPath : API_BASE + imgPath;
            img.className = "chat-embedded-image";
            img.onclick = () => window.open(img.src, '_blank');
            
            const dll = document.createElement("a");
            
            // Map strictly to the custom API download route to inherently bypass StaticFiles CORS boundaries
            const formattedPath = imgPath.startsWith("/") ? imgPath : "/" + imgPath;
            dll.href = `${API_BASE}/api/download?path=${encodeURIComponent(formattedPath)}`;
            
            dll.className = "chat-img-dl-btn";
            dll.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>`;
            dll.title = "Download Image";
            
            wrap.appendChild(img);
            wrap.appendChild(dll);
            imagesContainer.appendChild(wrap);
        });
        wrapper.appendChild(imagesContainer);
    }

    // Sources (bot only)
    if (entry.role === "bot" && entry.sources && entry.sources.length > 0) {
        const sourcesRow = document.createElement("div");
        sourcesRow.className = "chat-sources";
        entry.sources.forEach(src => {
            const pill = document.createElement("span");
            pill.className = "chat-source-pill";
            pill.innerHTML = `
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></svg>
                ${escapeHTML(src)}
            `;
            sourcesRow.appendChild(pill);
        });
        wrapper.appendChild(sourcesRow);
    }

    // Chunks accordion (bot only)
    if (entry.role === "bot" && entry.chunks && entry.chunks.length > 0) {
        const toggle = document.createElement("button");
        toggle.className = "chat-chunks-toggle";
        toggle.innerHTML = `
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10H3M21 6H3M21 14H3M21 18H3"/></svg>
            View ${entry.chunks.length} retrieved context chunk${entry.chunks.length > 1 ? "s" : ""}
        `;

        const panel = document.createElement("div");
        panel.className = "chat-chunks-panel";

        entry.chunks.forEach(chunk => {
            const card = document.createElement("div");
            card.className = "chat-chunk-card";
            const scoreLabel = typeof chunk.score === "number" ? chunk.score.toFixed(4) : "—";
            card.innerHTML = `
                <div class="chat-chunk-meta">
                    <span>${escapeHTML(chunk.file_name)} · Page ${chunk.page_number}</span>
                    <span>Score ${scoreLabel} · ${escapeHTML(chunk.method || "")}</span>
                </div>
                <div>${escapeHTML(chunk.content)}</div>
            `;
            panel.appendChild(card);
        });

        toggle.addEventListener("click", () => {
            const open = panel.classList.toggle("open");
            toggle.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10H3M21 6H3M21 14H3M21 18H3"/></svg>
                ${open ? "Hide" : "View"} ${entry.chunks.length} retrieved context chunk${entry.chunks.length > 1 ? "s" : ""}
            `;
        });

        wrapper.appendChild(toggle);
        wrapper.appendChild(panel);
    }

    chatMessages.appendChild(wrapper);
    if (animate) scrollToBottom();
}

// ---------- Typing indicator ----------
function addTypingIndicator() {
    const wrapper = document.createElement("div");
    wrapper.className = "chat-message bot";
    wrapper.id = "typing-indicator-row";

    const indicator = document.createElement("div");
    indicator.className = "typing-indicator";
    indicator.innerHTML = `<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>`;

    wrapper.appendChild(indicator);
    chatMessages.appendChild(wrapper);
    scrollToBottom();
    return wrapper;
}

// ---------- Progress ----------
function updateProgress(percent, stage) {
    progressContainer.style.display = "flex";
    progressBar.style.width = `${percent}%`;
    progressStage.textContent = stage;
    progressPercent.textContent = `${percent}%`;
}

// ---------- Helpers ----------
function appendToHistory(entry) {
    if (!chatSessions[currentChatId]) return;
    const session = chatSessions[currentChatId];
    
    // Set title on first message
    if (session.messages.length === 0 && entry.role === "user") {
        session.title = entry.text.substring(0, 35) + (entry.text.length > 35 ? "..." : "");
    }
    
    session.messages.push(entry);
    session.updatedAt = Date.now();
    saveSessions();
    renderSidebar(); // to update order and title if needed
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function setLoading(on) {
    askBtn.disabled = on;
    askLoader.style.display = on ? "inline-block" : "none";
    if (sendIcon) sendIcon.style.display = on ? "none" : "inline";
}

function formatTime(ts) {
    const d = new Date(ts);
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

function escapeHTML(str) {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
}

// ---------- File upload ----------
fileInput.addEventListener("change", () => {
    const files = Array.from(fileInput.files);
    files.forEach(file => {
        const isDup = stagedFiles.some(f => f.name === file.name && f.size === file.size);
        if (!isDup) stagedFiles.push(file);
    });
    fileInput.value = "";
    renderQueue();
});

function renderQueue() {
    fileQueue.innerHTML = "";
    const label = document.querySelector(".custom-file-upload span");
    if (stagedFiles.length === 0) {
        label.textContent = "Choose Files";
        label.style.color = "var(--text-muted)";
        uploadBtn.disabled = true;
        return;
    }
    uploadBtn.disabled = false;
    label.textContent = `${stagedFiles.length} ${stagedFiles.length === 1 ? "file" : "files"} in queue`;
    label.style.color = "var(--primary)";

    stagedFiles.forEach((file, index) => {
        const item = document.createElement("div");
        item.className = "file-item";
        const info = document.createElement("div");
        info.className = "file-item-info";
        info.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span class="file-item-name">${escapeHTML(file.name)}</span>
        `;
        const removeBtn = document.createElement("button");
        removeBtn.className = "file-item-remove";
        removeBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>`;
        removeBtn.addEventListener("click", () => { stagedFiles.splice(index, 1); renderQueue(); });
        item.appendChild(info);
        item.appendChild(removeBtn);
        fileQueue.appendChild(item);
    });
}

uploadBtn.addEventListener("click", async () => {
    if (stagedFiles.length === 0) { showStatus("Please select at least one file.", "error"); return; }
    uploadBtn.disabled = true;
    showStatus(`Uploading ${stagedFiles.length} file(s)...`, "success");
    try {
        let ok = 0;
        for (const file of stagedFiles) {
            const fd = new FormData();
            fd.append("file", file);
            const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: fd });
            if (res.ok) ok++;
        }
        showStatus(`Successfully indexed ${ok} file(s).`, "success");
        stagedFiles = [];
        renderQueue();
        fetchLibrary();
    } catch {
        showStatus("Connection error. Is the server running?", "error");
    } finally {
        uploadBtn.disabled = stagedFiles.length === 0;
    }
});

// ---------- Library ----------
async function fetchLibrary() {
    try {
        const res = await fetch(`${API_BASE}/documents`);
        if (!res.ok) throw new Error();
        renderLibrary(await res.json());
    } catch {
        libraryList.innerHTML = `<p class="section-desc" style="color:#ff453a">Failed to load library.</p>`;
    }
}

function renderLibrary(docs) {
    libraryList.innerHTML = "";
    libraryCount.textContent = `${docs.length} ${docs.length === 1 ? "Document" : "Documents"}`;
    if (docs.length === 0) {
        libraryList.innerHTML = `<p class="section-desc">Knowledge base is empty. Upload documents to get started.</p>`;
        return;
    }
    docs.forEach(doc => {
        const item = document.createElement("div");
        item.className = "library-item";
        const content = document.createElement("div");
        content.className = "library-item-content";
        const date = new Date(doc.upload_time).toLocaleDateString(undefined, {
            month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit"
        });
        content.innerHTML = `
            <span class="library-item-name">${escapeHTML(doc.file_name)}</span>
            <span class="library-item-meta">Indexed on ${date}</span>
        `;
        const actions = document.createElement("div");
        actions.className = "library-item-actions";
        const delBtn = document.createElement("button");
        delBtn.className = "btn-icon-delete";
        delBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18m-2 0v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6m3 0V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>`;
        delBtn.onclick = () => showDeleteModal("document", doc.id, doc.file_name);
        actions.appendChild(delBtn);
        item.appendChild(content);
        item.appendChild(actions);
        libraryList.appendChild(item);
    });
}

function showStatus(text, type) {
    uploadStatus.textContent = text;
    uploadStatus.className = `status ${type}`;
    if (type === "success") setTimeout(() => { if (uploadStatus.textContent === text) uploadStatus.textContent = ""; }, 5000);
}

// ---------- Delete modal ----------
function showDeleteModal(type, id, displayName) {
    pendingDeleteType = type;
    pendingDeleteId = id;
    
    if (type === "document") {
        modalTitle.textContent = "Delete Document?";
        modalMessage.textContent = `Are you sure you want to delete "${displayName}"? This will remove all associated context.`;
    } else {
        modalTitle.textContent = "Delete Chat?";
        modalMessage.textContent = `Are you sure you want to delete "${displayName}"? This conversation history will be lost.`;
    }
    
    confirmModal.style.display = "flex";
}

modalCancel.onclick = () => { 
    confirmModal.style.display = "none"; 
    pendingDeleteId = null; 
    pendingDeleteType = null;
};

modalConfirm.onclick = async () => {
    if (!pendingDeleteId || !pendingDeleteType) return;
    
    modalConfirm.disabled = true;
    modalConfirm.textContent = "Deleting...";
    
    try {
        if (pendingDeleteType === "document") {
            const res = await fetch(`${API_BASE}/documents/${pendingDeleteId}`, { method: "DELETE", mode: "cors" });
            if (!res.ok) throw new Error();
            showStatus("Document deleted.", "success");
            fetchLibrary();
        } else {
            executeChatDelete(pendingDeleteId);
        }
    } catch {
        alert("Failed to delete. Ensure the server is running.");
    } finally {
        modalConfirm.disabled = false;
        modalConfirm.textContent = "Delete Now";
        confirmModal.style.display = "none";
        pendingDeleteId = null;
        pendingDeleteType = null;
    }
};

window.onclick = e => { if (e.target === confirmModal) modalCancel.onclick(); };
