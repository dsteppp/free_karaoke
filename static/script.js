// ─────────────────────────────────────────────────────────────────────────────
// Глобальное состояние
// ─────────────────────────────────────────────────────────────────────────────
let allTracks = [];
const instAudio = new Audio();
const vocAudio  = new Audio();

// Экспортируем в глобальную область видимости для editor.js
window.instAudio = instAudio;
window.vocAudio = vocAudio;

let lyricsData  = [];
let playerLines = []; // Кэшированная структура
let animationFrameId = null;
let pollingInterval  = null;
let currentTrack     = null;
let isSeeking        = false;
let lastActiveLineIdx = -1;
let lastScrollTarget  = -1; 
let currentVisualProgress = 0;
let targetProgress        = 0;
let animationFrameIdProgress = null;

const VISUAL_OFFSET       = 0;
const LINE_PRE_ACTIVATION = 0.35; 

const fallbackCover = `data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='%2394a3b8' viewBox='0 0 24 24'%3E%3Cpath d='M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z'/%3E%3C/svg%3E`;

// ─────────────────────────────────────────────────────────────────────────────
// Ссылки на DOM-элементы
// ─────────────────────────────────────────────────────────────────────────────
const els = {
    fileInput:   document.getElementById("audio-files"),
    progBox:     document.getElementById("upload-progress-box"),
    progFill:    document.getElementById("upload-fill"),
    progStat:    document.getElementById("upload-status"),
    progPct:     document.getElementById("progress-percent"),
    cancelBtn:   document.getElementById("cancel-btn"),
    scanBtn:     document.getElementById("scan-btn"),
    clearBtn:    document.getElementById("clear-btn"),
    layout:      document.getElementById("main-layout"),
    list:        document.getElementById("tracks-list"),
    kCont:       document.getElementById("karaoke-container"),
    playBtn:     document.getElementById("play-btn"),
    stopBtn:     document.getElementById("stop-btn"),
    vInst:       document.getElementById("vol-inst"),
    vVoc:        document.getElementById("vol-voc"),
    lInst:       document.getElementById("lbl-inst"),
    lVoc:        document.getElementById("lbl-voc"),
    seek:        document.getElementById("seek-bar"),
    tCurr:       document.getElementById("time-current"),
    tTot:        document.getElementById("time-total"),
    lDisp:       document.getElementById("lyrics-display"),
    lWrap:       document.getElementById("lyrics-wrapper"),
    fsBtn:       document.getElementById("fs-btn"),
    sInput:      document.getElementById("search-input"),
    sClear:      document.getElementById("search-clear-btn"),
    sByBtn:      document.getElementById("sort-by-btn"),
    sDirBtn:     document.getElementById("sort-dir-btn"),
    statArtists: document.getElementById("stat-artists"),
    statTracks:  document.getElementById("stat-tracks"),
    // Строка состояния
    statusBar:   document.getElementById("app-status-bar"),
    statusText:  document.getElementById("app-status-text"),
    statusSpinner: document.getElementById("app-status-spinner"),
    statusProgress: document.getElementById("app-status-progress"),
    statusProgressFill: document.getElementById("app-status-progress-fill"),
};

// ─────────────────────────────────────────────────────────────────────────────
// Привязка событий
// ─────────────────────────────────────────────────────────────────────────────
els.fileInput.addEventListener("change", uploadFiles);
els.cancelBtn.addEventListener("click",  cancelProcessing);
els.scanBtn.addEventListener("click",    scanLibrary);
els.clearBtn.addEventListener("click",   clearLibrary);
els.playBtn.addEventListener("click",    togglePlay);
els.stopBtn.addEventListener("click",    stopPlay);
els.vInst.addEventListener("input",      updateVolumes);
els.vVoc.addEventListener("input",       updateVolumes);
els.fsBtn.addEventListener("click",      toggleFS);

// ── Файловый диалог: вызываем yad через pywebview API ──────────────────────
// yad работает 100% офлайн, не зависит от Qt/NFS
const uploadLabel = document.querySelector('label[for="audio-files"]');
if (uploadLabel) {
    uploadLabel.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        openNativeFileDialog();
    });
}

async function openNativeFileDialog() {
    try {
        if (!window.pywebview || !window.pywebview.api) {
            console.warn("pywebview API недоступен, fallback на HTML input");
            els.fileInput.click();
            return;
        }
        const files = await window.pywebview.api.open_file_dialog(true);
        console.log("[upload] Выбранные файлы:", files);
        if (files && files.length > 0) {
            const res = await fetch("/api/upload-from-paths", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ paths: files }),
            });
            if (res.ok) {
                await loadTracks();
                startPolling();
            }
        }
    } catch (e) {
        console.warn("Нативный диалог не сработал:", e);
        els.fileInput.click();
    }
}

// ГОРЯЧИЕ КЛАВИШИ (Плей/Пауза, Перемотка, Fullscreen, Редактор)
document.addEventListener("keydown", (e) => {
    // Игнорируем нажатия, если пользователь вводит текст (поиск или редактор слов)
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    if (e.key === "Escape" && document.body.classList.contains("fs-mode")) {
        toggleFS();
        return;
    }

    // R — вкл/выкл редактор (любая раскладка,物理ческая клавиша R)
    if (e.code === "KeyR") {
        e.preventDefault();
        const editorStartBtn = document.getElementById("edit-start-btn");
        if (editorStartBtn) editorStartBtn.click();
        return;
    }

    // F — вкл/выкл фуллскрин (любая раскладка, физическая клавиша F)
    if (e.code === "KeyF") {
        e.preventDefault();
        toggleFS();
        return;
    }

    if (e.code === "Space") {
        e.preventDefault(); // Чтобы страница не прокручивалась вниз
        togglePlay();
        return;
    }

    if (e.code === "ArrowLeft") {
        e.preventDefault();
        skipTime(-5);
        return;
    }

    if (e.code === "ArrowRight") {
        e.preventDefault();
        skipTime(5);
        return;
    }
});

// Функция перемотки для горячих клавиш
function skipTime(delta) {
    if (!currentTrack || !instAudio.src) return;
    let newTime = instAudio.currentTime + delta;
    newTime = Math.max(0, Math.min(newTime, instAudio.duration || 0));
    els.seek.value = newTime;
    els.seek.dispatchEvent(new Event("change"));
}

window.addEventListener("resize", () => {
    if (lastScrollTarget !== -1) scrollToActiveLine(lastScrollTarget, "auto");
});

[{ el: els.vInst, def: 1 }, { el: els.vVoc, def: 0.2 }].forEach(item => {
    let lastTap = 0;
    item.el.parentElement.addEventListener("pointerdown", (e) => {
        const now = Date.now();
        if (now - lastTap < 300) {
            item.el.value = item.def;
            item.el.dispatchEvent(new Event("input"));
            e.preventDefault();
        }
        lastTap = now;
    });
});

els.sInput.addEventListener("input", () => {
    els.sClear.style.display = els.sInput.value.length > 0 ? "flex" : "none";
    renderList();
});
els.sClear.addEventListener("click", () => {
    els.sInput.value = "";
    els.sClear.style.display = "none";
    renderList();
});

els.sByBtn.addEventListener("click", () => {
    const isArtist = els.sByBtn.getAttribute("data-sort") === "artist";
    els.sByBtn.setAttribute("data-sort", isArtist ? "title" : "artist");
    document.getElementById("sort-text-label").innerText = isArtist ? "Трек" : "Артист";
    document.getElementById("icon-artist").style.display = isArtist ? "none"  : "block";
    document.getElementById("icon-title").style.display  = isArtist ? "block" : "none";
    renderList();
});

els.sDirBtn.addEventListener("click", (e) => {
    const b = e.currentTarget;
    const d = b.getAttribute("data-dir");
    b.setAttribute("data-dir", d === "asc" ? "desc" : "asc");
    renderList();
});

instAudio.addEventListener("loadedmetadata", () => {
    els.seek.max = instAudio.duration;
    els.tTot.innerText = fmtTime(instAudio.duration);
});
instAudio.addEventListener("ended", stopPlay);

els.seek.addEventListener("input", () => { 
    isSeeking = true; 
    els.tCurr.innerText = fmtTime(els.seek.value); 
});

els.seek.addEventListener("change", () => {
    const val = parseFloat(els.seek.value);
    instAudio.currentTime = val;
    vocAudio.currentTime = val;
    isSeeking = false;
    
    lastActiveLineIdx = -1;
    forceRepaintFills(val);
    
    if (!instAudio.paused) {
        vocAudio.play().catch(()=>{});
        instAudio.play().catch(()=>{});
    }
});

let fsTout = null;
document.addEventListener("mousemove", () => {
    if (document.body.classList.contains("fs-mode")) {
        els.lWrap.style.cursor = "default";
        clearTimeout(fsTout);
        fsTout = setTimeout(() => {
            if (document.body.classList.contains("fs-mode"))
                els.lWrap.style.cursor = "none";
        }, 2000);
    } else {
        els.lWrap.style.cursor = "default";
        clearTimeout(fsTout);
    }
});

// КЛИК-ПЕРЕМОТКА ПО СЛОВАМ (В ОБЫЧНОМ РЕЖИМЕ)
els.lDisp.addEventListener("click", (e) => {
    if (document.body.classList.contains("edit-mode")) return; 
    
    const target = e.target.closest(".word");
    if (!target) return;

    const idx = parseInt(target.dataset.index, 10);
    if (!isNaN(idx) && window.lyricsData && window.lyricsData[idx]) {
        const t = window.lyricsData[idx].start;
        instAudio.currentTime = t;
        vocAudio.currentTime = t;
        els.seek.value = t;
        els.seek.dispatchEvent(new Event("change"));
    }
});

// ─────────────────────────────────────────────────────────────────────────────
// Утилиты
// ─────────────────────────────────────────────────────────────────────────────
function fmtTime(s) {
    if (isNaN(s)) return "0:00";
    return `${Math.floor(s / 60)}:${Math.floor(s % 60).toString().padStart(2, "0")}`;
}

function esc(t) {
    return String(t).replace(/[&<>"']/g, m => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]
    ));
}

function highlightText(text, term) {
    if (!term) return esc(text);
    const safe = esc(term).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return esc(text).replace(new RegExp(`(${safe})`, "gi"), '<span class="highlight">$1</span>');
}

// ─────────────────────────────────────────────────────────────────────────────
// Загрузка и поллинг
// ─────────────────────────────────────────────────────────────────────────────
async function loadTracks() {
    try {
        const r = await fetch("/api/status");
        const d = await r.json();
        allTracks = d.tracks;
        renderList();
        updateAppStatus(); // Инициализация строки состояния
        if (d.tracks.some(t => t.status !== "done" && t.status !== "error"))
            startPolling();
    } catch (e) { console.error(e); }
}

// ── Глобальное состояние для отслеживания статуса треков ──
let prevTrackStatus = {};
let lastRenderHash = ""; // Для предотвращения лишних перерисовок

function startPolling() {
    if (pollingInterval) return;

    pollingInterval = setInterval(async () => {
        try {
            const r = await fetch("/api/status");
            const d = await r.json();
            const newTracks = d.tracks;

            // Проверяем, изменились ли данные — хэш по статусам
            const hash = newTracks.map(t => `${t.id}:${t.status}`).join("|");
            if (hash === lastRenderHash) return; // Ничего не изменилось — не перерисовываем
            lastRenderHash = hash;

            allTracks = newTracks;
            renderList();

            // Обновляем текст кнопки сохранения если идёт перескан текущего трека
            if (metaEditingTrackId) {
                const editing = d.tracks.find(t => t.id === metaEditingTrackId);
                if (editing && editing.status !== "done" && editing.status !== "error") {
                    const saveBtn = document.getElementById("meta-save-btn");
                    if (saveBtn && saveBtn.classList.contains("saving")) {
                        saveBtn.querySelector("span").textContent = editing.status;
                    }
                }
            }

            // Перезагружаем плеер только если статус трека изменился на "done"
            if (currentTrack) {
                const updated = d.tracks.find(t => t.id === currentTrack.id);
                const wasDone = prevTrackStatus[currentTrack.id] === "done";
                const isDone = updated && updated.status === "done";
                if (isDone && !wasDone) {
                    prevTrackStatus[currentTrack.id] = "done";
                    loadKar(currentTrack, document.getElementById("cover-img").src);
                } else if (updated) {
                    prevTrackStatus[currentTrack.id] = updated.status;
                }
            }
        } catch (e) { console.error(e); }

        // Обновляем строку состояния (каждый цикл polling)
        updateAppStatus();
    }, 2000);
}

// ─── Строка состояния приложения ───────────────────────────────────────────
async function updateAppStatus() {
    try {
        const r = await fetch("/api/app-status");
        const d = await r.json();

        if (d.active && d.message) {
            els.statusBar.style.display = "";
            els.statusText.textContent = d.message;

            if (d.progress !== null && d.progress !== undefined) {
                // Прогресс-бар
                els.statusSpinner.style.display = "none";
                els.statusProgress.style.display = "";
                els.statusProgressFill.style.width = d.progress + "%";
            } else {
                // Спиннер
                els.statusSpinner.style.display = "";
                els.statusProgress.style.display = "none";
            }
        } else {
            // Ничего не происходит — строка пустая (просто отступ)
            els.statusText.textContent = "";
            els.statusSpinner.style.display = "none";
            els.statusProgress.style.display = "none";
            els.statusProgressFill.style.width = "0%";
        }
    } catch (e) {
        // Сеть недоступна — не показываем ошибку в строке состояния
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Анимация прогресс-бара (плавная интерполяция)
// ─────────────────────────────────────────────────────────────────────────────
function animProg() {
    currentVisualProgress += (targetProgress - currentVisualProgress) * 0.05;
    if (targetProgress === 100 && currentVisualProgress > 99) currentVisualProgress = 100;
    els.progFill.style.width = `${Math.min(currentVisualProgress, 100)}%`;
    const pctEl = document.getElementById("progress-percent");
    if (pctEl) pctEl.textContent = `${Math.round(currentVisualProgress)}%`;
    animationFrameIdProgress = requestAnimationFrame(animProg);
}

// ─────────────────────────────────────────────────────────────────────────────
// Рендер списка треков
// ─────────────────────────────────────────────────────────────────────────────
function renderList() {
    els.list.innerHTML = "";
    const term = els.sInput.value.toLowerCase().trim();

    let arr = term
        ? allTracks.filter(t => {
            const cl = (t.lyrics_text || "").replace(/$$.*?$$/g, "");
            return (t.title  || t.original_name || "").toLowerCase().includes(term)
                || (t.artist || "").toLowerCase().includes(term)
                || cl.toLowerCase().includes(term);
        })
        : [...allTracks];

    const by  = els.sByBtn.getAttribute("data-sort");
    const dir = els.sDirBtn.getAttribute("data-dir") === "asc" ? 1 : -1;
    arr.sort((a, b) => {
        const vA = (by === "title" ? (a.title || a.original_name) : (a.artist || "яя")).toLowerCase();
        const vB = (by === "title" ? (b.title || b.original_name) : (b.artist || "яя")).toLowerCase();
        return vA < vB ? -dir : vA > vB ? dir : 0;
    });

    const done = allTracks.filter(t => t.status === "done");
    const artists = new Set(done.map(t => (t.artist || "").toLowerCase().trim()).filter(Boolean));
    els.statTracks.innerText  = done.length;
    els.statArtists.innerText = artists.size;

    if (!arr.length) {
        els.list.innerHTML = '<div style="color:var(--text-muted);padding:2rem;text-align:center;">Ничего не найдено</div>';
        return;
    }

    arr.forEach(t => {
        const row = document.createElement("div");
        row.className = "track-item";

        const img = document.createElement("img");
        img.className = "track-cover-sm";
        img.src = fallbackCover;
        if (t.status === "done") {
            const base = encodeURIComponent(t.filename.replace(/\.[^.]+$/, ""));
            fetch(`/library/${base}_library.json`)
                .then(r => r.json())
                .then(d => { if (d.cover) img.src = d.cover; })
                .catch(() => {});
        }

        const info   = document.createElement("div");
        info.className = "track-info";
        const ttl    = t.title  || t.original_name;
        const art    = t.artist || "Неизвестно";
        const stCls  = t.status === "done" ? "done" : t.status === "error" ? "error" : "";
        const errTip = t.error_message ? ` title="${esc(t.error_message)}"` : "";

        info.innerHTML =
            `<div class="title" title="${esc(ttl)}">${term ? highlightText(ttl, term) : esc(ttl)}</div>` +
            `<div class="artist">${term ? highlightText(art, term) : esc(art)}</div>` +
            `<div class="track-status ${stCls}"${errTip}>${esc(t.status)}</div>`;

        if (term && t.lyrics_text) {
            const cl = t.lyrics_text.replace(/$$.*?$$/g, "");
            if (cl.toLowerCase().includes(term)) {
                const ml = cl.split("\n").find(l => l.toLowerCase().includes(term) && l.trim());
                if (ml) {
                    const sn = document.createElement("div");
                    sn.className = "lyrics-snippet";
                    sn.innerHTML = highlightText(ml.trim(), term);
                    info.appendChild(sn);
                }
            }
        }

        const acts = document.createElement("div");
        acts.className = "track-actions";

        if (t.status === "done") {
            const pB = document.createElement("button");
            pB.className = "btn btn-primary btn-icon";
            pB.setAttribute("data-tooltip", "Воспроизвести");
            pB.setAttribute("data-tooltip-pos", "right");
            pB.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`;
            pB.onclick = () => loadKar(t, img.src);

            const rB = document.createElement("button");
            rB.className = "btn btn-surface btn-icon";
            rB.setAttribute("data-tooltip", "Пересинхронизировать текст");
            rB.setAttribute("data-tooltip-pos", "right");
            rB.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.3"/></svg>`;
            rB.onclick = () => apiReq(t.id, "reset_text");

            const eB = document.createElement("button");
            eB.className = "edit-meta-btn";
            eB.setAttribute("data-meta-track", t.id);
            eB.setAttribute("data-tooltip", "Редактировать метаданные");
            eB.setAttribute("data-tooltip-pos", "right");
            eB.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`;
            eB.onclick = () => openMetaEditor(t.id);

            acts.append(pB, rB, eB);
        }

        const dB = document.createElement("button");
        dB.className = "btn btn-danger-soft btn-icon";
        dB.setAttribute("data-tooltip", "Удалить трек");
        dB.setAttribute("data-tooltip-pos", "right");
        dB.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
        dB.onclick = () => apiReq(t.id, "del");
        acts.appendChild(dB);

        row.append(img, info, acts);
        els.list.appendChild(row);
    });
}

async function apiReq(id, act) {
    if (act === "del"        && !confirm("Удалить трек?"))         return;
    if (act === "reset_text" && !confirm("Пересинхронизировать?")) return;

    // Закрываем overlay если он открыт для этого трека
    if (metaEditingTrackId === id) closeMetaEditor();

    const url    = `/api/tracks/${id}${act === "reset_text" ? "/reset_text" : ""}`;
    const method = act === "del" ? "DELETE" : "POST";
    await fetch(url, { method });

    if (currentTrack && currentTrack.id === id) { stopPlay(); resetPlayerUI(); }
    loadTracks();
    if (act === "reset_text") startPolling();
}

function uploadFiles() {
    if (!els.fileInput.files.length) return;
    const fd = new FormData();
    for (const f of els.fileInput.files) fd.append("files", f);

    const x = new XMLHttpRequest();
    x.open("POST", "/api/upload", true);
    x.onload = async () => {
        els.fileInput.value = "";
        await loadTracks();
        startPolling();
    };
    x.send(fd);
}

async function cancelProcessing() {
    if (!confirm("Остановить все задачи?")) return;
    clearInterval(pollingInterval);
    pollingInterval = null;
    await fetch("/api/cancel", { method: "POST" });
    loadTracks();
}

async function scanLibrary() {
    await fetch("/api/scan", { method: "POST" });
    loadTracks();
    startPolling();
}

async function clearLibrary() {
    if (!confirm("Удалить ВСЁ из библиотеки?")) return;
    await fetch("/api/clear", { method: "DELETE" });
    stopPlay();
    resetPlayerUI();
    loadTracks();
}

function resetPlayerUI() {
    document.body.classList.remove("edit-mode", "popover-open");
    document.getElementById("cv-title").innerText  = "Трек не выбран";
    document.getElementById("cv-title").title      = "Трек не выбран";
    document.getElementById("cv-artist").innerText = "Артист не выбран";
    document.getElementById("cv-artist").title     = "Артист не выбран";
    document.getElementById("cover-img").src       = fallbackCover;
    const bg = document.getElementById("bg-img-1");
    bg.style.backgroundImage = "none";
    bg.className = "bg-slide";
    els.lDisp.innerHTML = "";
    currentTrack = null;
    window.currentTrack = null;
    playerLines = [];
}

async function loadKar(t, cvr) {
    stopPlay();
    document.body.classList.remove("edit-mode", "popover-open");

    currentTrack   = t;
    window.currentTrack = t;
    els.seek.value = 0;
    syncSliders();
    // Сброс скролла при загрузке трека — первая строка корректно позиционируется
    els.lDisp.scrollTop = 0;

    if (window.innerWidth <= 1024 && !document.body.classList.contains("fs-mode"))
        els.kCont.scrollIntoView({ behavior: "smooth" });

    const nm = t.title || t.original_name.replace(/\.[^.]+$/, "");
    document.getElementById("cv-title").innerText  = nm;
    document.getElementById("cv-title").title      = nm;
    document.getElementById("cv-artist").innerText = t.artist || "Unknown";
    document.getElementById("cv-artist").title     = t.artist || "Unknown";
    document.getElementById("cover-img").src       = cvr || fallbackCover;
    document.getElementById("bg-img-1").className  = "bg-slide";

    els.lDisp.innerHTML = '<div style="color:var(--text-muted);padding:2rem;">Загрузка...</div>';

    const bn = encodeURIComponent(t.filename.replace(/\.[^.]+$/, ""));
    instAudio.src = `/library/${bn}_(Instrumental).mp3`;
    vocAudio.src  = `/library/${bn}_(Vocals).mp3`;
    updateVolumes();

    try {
        const m = await fetch(`/library/${bn}_library.json`).then(r => r.json());
        if (m.cover) document.getElementById("cover-img").src = m.cover;
        if (m.bg || m.cover) {
            const bgEl = document.getElementById("bg-img-1");
            bgEl.style.backgroundImage = `url('${m.bg || m.cover}')`;
            bgEl.classList.add("active");
        }
        // Сохраняем artist/title из library.json для отображения в плеере
        if (m.artist) {
            document.getElementById("cv-artist").textContent = m.artist;
        }
        if (m.title) {
            document.getElementById("cv-title").textContent = m.title;
        }
    } catch (_) {}

    try {
        lyricsData = await fetch(`/library/${bn}_(Karaoke Lyrics).json`)
            .then(r => { if (!r.ok) throw new Error("no lyrics"); return r.json(); });

        window.lyricsData = lyricsData;

        let cur = [];
        let rawLines = [];
        for (const w of lyricsData) {
            cur.push(w);
            if (w.line_break) { if (cur.length) rawLines.push(cur); cur = []; }
        }
        if (cur.length) rawLines.push(cur);
        
        renderLyrics(rawLines);
        
        forceRepaintFills(instAudio.currentTime);
        
    } catch (_) {
        lyricsData = [];
        window.lyricsData = [];
        playerLines = [];
        els.lDisp.innerHTML = '<div style="color:var(--warning);padding:2rem;">Текст не готов</div>';
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// РЕНДЕР
// ─────────────────────────────────────────────────────────────────────────────
function renderLyrics(rawLines) {
    els.lDisp.innerHTML = "";
    playerLines = []; 
    let globalWordIndex = 0; 

    rawLines.forEach((lineArr, lineIndex) => {
        const div = document.createElement("div");
        div.className = "lyric-line future-far";
        
        const lineObj = {
            domNode: div,
            start: parseFloat(lineArr[0].start),
            end: parseFloat(lineArr[lineArr.length - 1].end),
            words: []
        };

        lineArr.forEach((w, wIdx) => {
            const wordSpan = document.createElement("span");
            wordSpan.className = "word";
            wordSpan.textContent = w.word;
            wordSpan.dataset.index = globalWordIndex++; 
            
            if (w.is_manual_start) wordSpan.classList.add("manual-start");
            if (w.is_manual_end) wordSpan.classList.add("manual-end");
            if (w.is_manual_text) wordSpan.classList.add("manual-text");
            
            lineObj.words.push({
                domNode: wordSpan,
                start: parseFloat(w.start),
                end: parseFloat(w.end),
                lastPct: "-1" 
            });
            
            div.appendChild(wordSpan);
            
            if (!w.line_break && wIdx !== lineArr.length - 1) {
                div.appendChild(document.createTextNode(" "));
            }
        });

        els.lDisp.appendChild(div);
        playerLines.push(lineObj);
    });
    
    window.playerLines = playerLines;
}

// ─────────────────────────────────────────────────────────────────────────────
// ПРОКРУТКА
// ─────────────────────────────────────────────────────────────────────────────
function scrollToActiveLine(idx, behavior = 'smooth') {
    if (document.body.classList.contains("edit-mode")) return; 

    if (idx < 0 || idx >= playerLines.length) return;
    const container = els.lDisp;
    const lineNode = playerLines[idx].domNode;
    
    // Адаптивный offset: 40% от верха блока плеера в любом режиме
    const playerPanel = els.kCont;
    const playerHeight = playerPanel ? playerPanel.clientHeight : container.clientHeight;
    const offsetRatio = 0.40;
    const offset = lineNode.offsetTop - (playerHeight * offsetRatio) + (lineNode.clientHeight / 2);
    container.scrollTo({ top: Math.max(0, offset), behavior: behavior });
}
window.scrollToActiveLine = scrollToActiveLine; // Доступен из editor.js

// ─────────────────────────────────────────────────────────────────────────────
// ПЛЕЕР И АНИМАЦИЯ
// ─────────────────────────────────────────────────────────────────────────────
async function togglePlay() {
    if (!instAudio.src) return;

    if (instAudio.paused) {
        vocAudio.currentTime = instAudio.currentTime;
        try {
            await Promise.all([instAudio.play(), vocAudio.play()]);
        } catch (e) {
            console.error("Ошибка воспроизведения:", e);
            return;
        }
        els.playBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="4" width="4" height="16"/>
            <rect x="14" y="4" width="4" height="16"/>
        </svg>`;
        loop();
    } else {
        instAudio.pause();
        vocAudio.pause();
        els.playBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`;
        cancelAnimationFrame(animationFrameId);
    }
}

function stopPlay() {
    instAudio.pause();
    vocAudio.pause();
    instAudio.currentTime = vocAudio.currentTime = 0;
    els.seek.value  = 0;
    els.tCurr.innerText = "0:00";
    els.playBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`;
    cancelAnimationFrame(animationFrameId);

    lastActiveLineIdx = -1;
    lastScrollTarget  = -1;
    forceRepaintFills(0);
    
    if (playerLines.length > 0 && !document.body.classList.contains("edit-mode")) {
        els.lDisp.scrollTop = 0;
    }
}

function forceRepaintFills(time) {
    if (!playerLines.length) return;
    
    updateLineClasses(time);
    
    playerLines.forEach(line => {
        line.words.forEach(word => {
            let pct = 0;
            if (time >= word.end) pct = 100;
            else if (time > word.start) pct = ((time - word.start) / (word.end - word.start)) * 100;
            
            const roundedPct = pct.toFixed(1);
            if (word.lastPct !== roundedPct) {
                word.domNode.style.setProperty("--fill", `${roundedPct}%`);
                word.lastPct = roundedPct;
            }
        });
    });
}

function updateLineClasses(t) {
    let activeIdx = -1;
    let anchor = playerLines.length;

    for (let i = 0; i < playerLines.length; i++) {
        const line = playerLines[i];
        if (t >= line.start - LINE_PRE_ACTIVATION) {
            activeIdx = i; 
        } else {
            break; 
        }
    }

    if (activeIdx !== -1) {
        if (t > playerLines[activeIdx].end + 0.5) {
            activeIdx = -1;
        }
    }

    if (activeIdx === -1) {
        for (let i = 0; i < playerLines.length; i++) {
            if (t < playerLines[i].start) {
                anchor = i;
                break;
            }
        }
    } else {
        anchor = activeIdx;
    }

    const scrollTarget = activeIdx !== -1 ? activeIdx : Math.min(anchor, playerLines.length - 1);
    
    if (scrollTarget !== lastScrollTarget) {
        lastScrollTarget = scrollTarget;
        if (!isSeeking && scrollTarget >= 0) {
            scrollToActiveLine(scrollTarget, "smooth");
        } else if (isSeeking && scrollTarget >= 0) {
            scrollToActiveLine(scrollTarget, "auto");
        }
    }

    lastActiveLineIdx = activeIdx;

    for (let i = 0; i < playerLines.length; i++) {
        const l = playerLines[i].domNode;
        let newClass = "lyric-line ";
        
        if (i === activeIdx) {
            newClass += "active-line";
        } else if (i < anchor) {
            const d = anchor - i;
            newClass += (d === 1 ? "past-0" : d === 2 ? "past-1" : "past-far");
        } else {
            const center = activeIdx !== -1 ? activeIdx : anchor - 1;
            const d = i - center;
            newClass += (d === 1 ? "future-1" : d === 2 ? "future-2" : "future-far");
        }
        
        if (l.className !== newClass) {
            l.className = newClass;
        }
    }
}

function loop() {
    if (instAudio.paused && !isSeeking) return;

    const t = instAudio.currentTime;

    if (!isSeeking) {
        els.seek.value = t;
        els.tCurr.innerText = fmtTime(t);
    }

    if (playerLines.length > 0) {
        const visualTime = t + VISUAL_OFFSET;
        updateLineClasses(visualTime);

        const sIdx = Math.max(0, (lastScrollTarget === -1 ? 0 : lastScrollTarget - 2));
        const eIdx = Math.min(playerLines.length - 1, (lastScrollTarget === -1 ? playerLines.length - 1 : lastScrollTarget + 2));
        
        for (let i = sIdx; i <= eIdx; i++) {
            const line = playerLines[i];
            for (let j = 0; j < line.words.length; j++) {
                const word = line.words[j];
                let pct = 0;
                
                if (visualTime >= word.end) {
                    pct = 100;
                } else if (visualTime > word.start) {
                    pct = ((visualTime - word.start) / (word.end - word.start)) * 100;
                }
                
                const roundedPct = pct.toFixed(1);
                if (word.lastPct !== roundedPct) {
                    word.domNode.style.setProperty("--fill", `${roundedPct}%`);
                    word.lastPct = roundedPct;
                }
            }
        }
    }

    if (!instAudio.paused) {
        animationFrameId = requestAnimationFrame(loop);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Громкость и UI
// ─────────────────────────────────────────────────────────────────────────────
function updateVolumes() {
    instAudio.volume = parseFloat(els.vInst.value);
    vocAudio.volume  = parseFloat(els.vVoc.value);
    els.lInst.innerText = `${Math.round(instAudio.volume * 100)}%`;
    els.lVoc.innerText  = `${Math.round(vocAudio.volume  * 100)}%`;
    syncSliders();
}

function syncSliders() {
    [
        { i: els.vInst, l: els.lInst },
        { i: els.vVoc,  l: els.lVoc  },
    ].forEach(obj => {
        if (!obj.i || !obj.l) return;
        const min = parseFloat(obj.i.min) || 0;
        const max = parseFloat(obj.i.max) || 1;
        const val = parseFloat(obj.i.value);
        const pct = max === min ? 0 : (val - min) / (max - min);
        obj.i.parentElement.style.setProperty("--pct", pct);
    });
}

function toggleFS() {
    const isFS = document.body.classList.contains("fs-mode");
    document.body.classList.toggle("fs-mode", !isFS);
    setTimeout(() => {
        if (lastScrollTarget !== -1) scrollToActiveLine(lastScrollTarget, "auto");
    }, 50);
}

syncSliders();
loadTracks();

// ════════════════════════════════════════════════════════════════════════════════
// OVERLAY: Редактирование метаданных (внутри плеера)
// ════════════════════════════════════════════════════════════════════════════════

let metaEditingTrackId = null;
let metaOriginalData = null;
let metaCoverBase64 = null;
let metaBgBase64 = null;
let metaCoverGeniusUrl = null;
let metaBgGeniusUrl = null;

// Прозрачный placeholder 1x1 для img без src
const TRANSPARENT_PLACEHOLDER = "data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==";

// Элементы overlay
const metaOverlay = document.getElementById("metadata-overlay");
const metaPanel = document.querySelector(".meta-panel");
const metaTitleInput = document.getElementById("meta-title-input");
const metaArtistInput = document.getElementById("meta-artist-input");
const metaLyricsInput = document.getElementById("meta-lyrics-input");
const metaRescanToggle = document.getElementById("meta-rescan-toggle");
const metaRescanHint = document.getElementById("meta-rescan-hint");
const metaCoverUrl = document.getElementById("meta-cover-url");
const metaBgUrl = document.getElementById("meta-bg-url");
const metaCoverPreview = document.getElementById("meta-cover-preview");
const metaBgPreview = document.getElementById("meta-bg-preview");
const metaCoverFileInput = document.getElementById("meta-cover-file-input");
const metaBgFileInput = document.getElementById("meta-bg-file-input");
const metaCoverDropzone = document.getElementById("meta-cover-dropzone");
const metaBgDropzone = document.getElementById("meta-bg-dropzone");

// Открытие overlay
function openMetaEditor(trackId) {
    const track = allTracks.find(t => t.id === trackId);
    if (!track || track.status !== "done") return;

    metaEditingTrackId = trackId;
    metaOriginalData = {
        artist: track.artist || "",
        title: track.title || "",
        lyrics: track.lyrics_text || "",
    };
    metaCoverBase64 = null;
    metaBgBase64 = null;
    metaCoverGeniusUrl = null;
    metaBgGeniusUrl = null;

    // Заполняем поля
    metaTitleInput.value = metaOriginalData.title;
    metaArtistInput.value = metaOriginalData.artist;
    metaLyricsInput.value = metaOriginalData.lyrics;
    metaRescanToggle.checked = false;
    metaRescanHint.style.display = "none";

    // Сбрасываем превью
    metaCoverPreview.src = TRANSPARENT_PLACEHOLDER;
    metaBgPreview.src = TRANSPARENT_PLACEHOLDER;
    metaCoverUrl.value = "";
    metaBgUrl.value = "";

    // Загружаем обложки из _library.json
    const base = encodeURIComponent(track.filename.replace(/\.[^.]+$/, ""));
    console.log("[meta] Loading covers for:", base);
    fetch(`/library/${base}_library.json`)
        .then(r => r.json())
        .then(m => {
            console.log("[meta] Got meta:", m);
            // Обложка трека
            const coverSrc = m.cover || "";
            if (coverSrc && coverSrc !== "") {
                if (coverSrc.startsWith("data:")) {
                    metaCoverBase64 = coverSrc;
                    metaCoverPreview.src = coverSrc;
                    metaCoverUrl.value = "";
                    console.log("[meta] Cover: base64");
                } else {
                    metaCoverUrl.value = coverSrc;
                    metaCoverPreview.src = coverSrc;
                    console.log("[meta] Cover URL:", coverSrc);
                }
            } else {
                metaCoverPreview.src = fallbackCover;
                console.log("[meta] Cover: using fallback");
            }
            metaCoverGeniusUrl = m.cover_genius || m.cover || "";

            // Фон плеера
            const bgSrc = m.bg || "";
            if (bgSrc && bgSrc !== "") {
                if (bgSrc.startsWith("data:")) {
                    metaBgBase64 = bgSrc;
                    metaBgPreview.src = bgSrc;
                    metaBgUrl.value = "";
                    console.log("[meta] BG: base64");
                } else {
                    metaBgUrl.value = bgSrc;
                    metaBgPreview.src = bgSrc;
                    console.log("[meta] BG URL:", bgSrc);
                }
            } else {
                metaBgPreview.src = fallbackCover;
                console.log("[meta] BG: using fallback");
            }
            metaBgGeniusUrl = m.bg_genius || m.bg || "";
        })
        .catch(err => {
            console.error("[meta] Failed to load meta.json:", err);
            metaCoverPreview.src = fallbackCover;
            metaBgPreview.src = fallbackCover;
        });

    metaOverlay.style.display = "flex";
    metaPanel.classList.remove("blocked");
    document.body.classList.add("meta-open");

    // Обновляем кнопку в строке трека
    const btn = document.querySelector(`[data-meta-track="${trackId}"]`);
    if (btn) btn.classList.add("active");
}

// Закрытие overlay
function closeMetaEditor() {
    metaOverlay.style.display = "none";
    metaEditingTrackId = null;
    metaOriginalData = null;
    metaCoverBase64 = null;
    metaBgBase64 = null;
    document.body.classList.remove("meta-open");

    const btn = document.querySelector(`[data-meta-track]`);
    if (btn) btn.classList.remove("active");
}

// Сохранение метаданных
async function saveMetaEditor() {
    if (!metaEditingTrackId) return;

    const saveBtn = document.getElementById("meta-save-btn");
    const cancelBtn = document.getElementById("meta-cancel-btn");

    saveBtn.classList.add("saving");
    saveBtn.querySelector("span").textContent = "Сохранение…";
    cancelBtn.style.display = "none";
    metaPanel.classList.add("blocked");

    const payload = {
        artist: metaArtistInput.value.trim(),
        title: metaTitleInput.value.trim(),
        lyrics: metaLyricsInput.value,
        rescan: metaRescanToggle.checked,
        cover_url: metaCoverBase64 ? null : (metaCoverUrl.value.trim() || null),
        cover_base64: metaCoverBase64,
        background_url: metaBgBase64 ? null : (metaBgUrl.value.trim() || null),
        background_base64: metaBgBase64,
    };
    const logPayload = {
        ...payload,
        cover_base64: metaCoverBase64 ? `(base64 ${metaCoverBase64.length} chars)` : null,
        background_base64: metaBgBase64 ? `(base64 ${metaBgBase64.length} chars)` : null,
    };
    console.log("[meta] Sending payload:", JSON.stringify(logPayload, null, 2));

    // При рескане запускаем polling ДО отправки — кнопка будет показывать текущий этап
    if (payload.rescan) startPolling();

    try {
        const res = await fetch(`/api/tracks/${metaEditingTrackId}/edit_metadata`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            let errMsg = `HTTP ${res.status}`;
            try {
                const errData = await res.json();
                // errData.detail может быть строкой, массивом или объектом
                if (typeof errData.detail === "string") {
                    errMsg = errData.detail;
                } else if (Array.isArray(errData.detail)) {
                    errMsg = errData.detail.map(d => d.msg || d).join("; ");
                } else if (typeof errData.detail === "object" && errData.detail !== null) {
                    errMsg = JSON.stringify(errData.detail);
                }
            } catch (_) {
                // не удалось распарсить JSON — оставляем HTTP статус
            }
            console.error("[edit_metadata] Ошибка сервера:", errMsg);
            throw new Error(errMsg);
        }

        console.log("[meta] Успешно сохранено");
        closeMetaEditor();
        loadTracks();

        // При рескане плеер обновится когда polling detect смену статуса на "done"
        if (!payload.rescan && currentTrack && currentTrack.id === metaEditingTrackId) {
            loadKar(currentTrack, document.getElementById("cover-img").src);
        }
    } catch (e) {
        console.error("[edit_metadata] Исключение:", e);
        alert("Ошибка при сохранении: " + e.message);
        metaPanel.classList.remove("blocked");
    } finally {
        saveBtn.classList.remove("saving");
        saveBtn.querySelector("span").textContent = "Сохранить";
        cancelBtn.style.display = "";
    }
}

// Сброс обложки к оригиналу от Genius
async function resetCoverToGenius() {
    if (!metaEditingTrackId) return;
    if (metaCoverGeniusUrl) {
        metaCoverUrl.value = metaCoverGeniusUrl;
        metaCoverBase64 = null;
        metaCoverPreview.src = metaCoverGeniusUrl;
    }
}

async function resetBgToGenius() {
    if (!metaEditingTrackId) return;
    if (metaBgGeniusUrl) {
        metaBgUrl.value = metaBgGeniusUrl;
        metaBgBase64 = null;
        metaBgPreview.src = metaBgGeniusUrl;
    }
}

// Обработка файлов обложек
function handleCoverFile(file) {
    console.log("[meta] handleCoverFile:", file ? file.name : "null", file ? file.type : "", file ? file.size : 0);
    if (!file || !file.type.startsWith("image/")) return;
    if (file.size > 5 * 1024 * 1024) {
        alert("Файл слишком большой (макс. 5 МБ)");
        return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
        console.log("[meta] Cover file loaded, base64 length:", e.target.result.length);
        metaCoverBase64 = e.target.result;
        metaCoverPreview.src = e.target.result;
        metaCoverUrl.value = "";
    };
    reader.onerror = (e) => console.error("[meta] Cover file read error:", e);
    reader.readAsDataURL(file);
}

function handleBgFile(file) {
    console.log("[meta] handleBgFile:", file ? file.name : "null", file ? file.type : "", file ? file.size : 0);
    if (!file || !file.type.startsWith("image/")) return;
    if (file.size > 5 * 1024 * 1024) {
        alert("Файл слишком большой (макс. 5 МБ)");
        return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
        console.log("[meta] BG file loaded, base64 length:", e.target.result.length);
        metaBgBase64 = e.target.result;
        metaBgPreview.src = e.target.result;
        metaBgUrl.value = "";
    };
    reader.onerror = (e) => console.error("[meta] BG file read error:", e);
    reader.readAsDataURL(file);
}

// Drag & Drop для обложек
function setupDropZone(dropzoneEl, fileInputEl, handler) {
    if (!dropzoneEl || !fileInputEl) {
        console.warn("[meta] setupDropZone: missing elements", dropzoneEl, fileInputEl);
        return;
    }
    console.log("[meta] setupDropZone:", dropzoneEl.id, fileInputEl.id);

    ["dragenter", "dragover"].forEach(evt => {
        dropzoneEl.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzoneEl.classList.add("drag-over");
        });
    });

    ["dragleave", "drop"].forEach(evt => {
        dropzoneEl.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzoneEl.classList.remove("drag-over");
        });
    });

    dropzoneEl.addEventListener("drop", (e) => {
        console.log("[meta] Drop event, files:", e.dataTransfer.files.length);
        const file = e.dataTransfer.files[0];
        if (file) handler(file);
    });

    fileInputEl.addEventListener("change", (e) => {
        console.log("[meta] File input change, files:", e.target.files.length);
        const file = e.target.files[0];
        if (file) handler(file);
        fileInputEl.value = "";
    });
}

// Обновление превью из URL при потере фокуса
function setupUrlPreview(urlInput, previewImg, base64VarName) {
    urlInput.addEventListener("blur", () => {
        const url = urlInput.value.trim();
        if (url && !url.startsWith("data:")) {
            previewImg.src = url;
            if (base64VarName === "cover") metaCoverBase64 = null;
            else metaBgBase64 = null;
        }
    });
}

// ── Привязка событий overlay ──────────────────────────────────────────────
document.getElementById("meta-close-btn").addEventListener("click", closeMetaEditor);
document.getElementById("meta-cancel-btn").addEventListener("click", closeMetaEditor);
document.getElementById("meta-save-btn").addEventListener("click", saveMetaEditor);
document.getElementById("meta-reset-cover-btn").addEventListener("click", resetCoverToGenius);
document.getElementById("meta-reset-bg-btn").addEventListener("click", resetBgToGenius);
document.getElementById("meta-cover-file-btn").addEventListener("click", () => metaCoverFileInput.click());
document.getElementById("meta-bg-file-btn").addEventListener("click", () => metaBgFileInput.click());

metaRescanToggle.addEventListener("change", () => {
    metaRescanHint.style.display = metaRescanToggle.checked ? "block" : "none";
});

// Drag & Drop — используем явные ID dropzone-элементов
setupDropZone(metaCoverDropzone, metaCoverFileInput, handleCoverFile);
setupDropZone(metaBgDropzone, metaBgFileInput, handleBgFile);

// Превью URL при blur
setupUrlPreview(metaCoverUrl, metaCoverPreview, "cover");
setupUrlPreview(metaBgUrl, metaBgPreview, "bg");

// Escape закрывает overlay
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && metaOverlay.style.display === "flex") {
        closeMetaEditor();
    }
});

// ── Кастомный ресайз textarea (только вертикально) ──────────────────────────────
const textareaWrapper = document.getElementById("meta-textarea-wrapper");
const textareaEl = document.getElementById("meta-lyrics-input");
let isResizing = false;
let resizeStartY = 0;
let resizeStartHeight = 0;

if (textareaWrapper && textareaEl) {
    textareaWrapper.addEventListener("mousedown", (e) => {
        // Проверяем что клик в правом нижнем углу (зона handle)
        const rect = textareaWrapper.getBoundingClientRect();
        if (e.clientX > rect.right - 24 && e.clientY > rect.bottom - 24) {
            isResizing = true;
            resizeStartY = e.clientY;
            resizeStartHeight = textareaEl.offsetHeight;
            e.preventDefault();
        }
    });

    document.addEventListener("mousemove", (e) => {
        if (!isResizing) return;
        const deltaY = e.clientY - resizeStartY;
        const newHeight = Math.max(120, Math.min(window.innerHeight * 0.5, resizeStartHeight + deltaY));
        textareaEl.style.height = newHeight + "px";
    });

    document.addEventListener("mouseup", () => {
        isResizing = false;
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// ГЛОБАЛЬНЫЙ ТУЛТИП
// ══════════════════════════════════════════════════════════════════════════════
(function() {
    const tooltip = document.createElement("div");
    tooltip.id = "global-tooltip";
    document.body.appendChild(tooltip);

    let currentTarget = null;
    let showTimeout = null;
    let hideTimeout = null;

    function showTooltip(el) {
        const text = el.getAttribute("data-tooltip");
        const shortcut = el.getAttribute("data-shortcut");
        if (!text) return;

        tooltip.innerHTML = esc(text);
        if (shortcut) {
            tooltip.innerHTML += ' <span class="tooltip-shortcut">' + esc(shortcut) + '</span>';
        }

        const rect = el.getBoundingClientRect();
        const pos = el.getAttribute("data-tooltip-pos") || "bottom";

        // Сброс классов позиции
        tooltip.classList.remove("pos-right");

        requestAnimationFrame(() => {
            const tw = tooltip.offsetWidth;
            const th = tooltip.offsetHeight;
            let left, top;

            if (pos === "top") {
                left = rect.left + rect.width / 2 - tw / 2;
                top = rect.top - th - 8;
            } else if (pos === "right") {
                left = rect.right + 8;
                top = rect.top + rect.height / 2 - th / 2;
                tooltip.classList.add("pos-right");
            } else {
                // bottom
                left = rect.left + rect.width / 2 - tw / 2;
                top = rect.bottom + 8;
            }

            left = Math.max(4, Math.min(left, window.innerWidth - tw - 4));
            top = Math.max(4, Math.min(top, window.innerHeight - th - 4));
            tooltip.style.left = left + "px";
            tooltip.style.top = top + "px";
        });

        tooltip.classList.remove("hiding");
        tooltip.classList.add("visible");
    }

    function hideTooltip() {
        tooltip.classList.remove("visible");
        tooltip.classList.add("hiding");
    }

    function scheduleShow(el) {
        clearTimeout(hideTimeout);
        showTimeout = setTimeout(() => showTooltip(el), 500);
    }

    function scheduleHide() {
        clearTimeout(showTimeout);
        hideTimeout = setTimeout(hideTooltip, 500);
    }

    document.addEventListener("mouseover", (e) => {
        const el = e.target.closest("[data-tooltip]");
        if (el && el !== currentTarget) {
            currentTarget = el;
            scheduleShow(el);
        }
    });

    document.addEventListener("mouseout", (e) => {
        const el = e.target.closest("[data-tooltip]");
        if (el) {
            const related = e.relatedTarget;
            if (!el.contains(related)) {
                currentTarget = null;
                scheduleHide();
            }
        }
    });

    document.addEventListener("scroll", () => {
        if (currentTarget && tooltip.classList.contains("visible")) {
            showTooltip(currentTarget);
        }
    }, true);
})();

// ══════════════════════════════════════════════════════════════════════════════
// ЭКСПОРТ / ИМПОРТ БИБЛИОТЕКИ
// ══════════════════════════════════════════════════════════════════════════════
(function() {
    const importBtn = document.getElementById("import-btn");
    const exportBtn = document.getElementById("export-btn");
    let isBusy = false; // Блокировка одновременных операций

    // Блокировка интерфейса во время операции
    function setBusy(busy, operation) {
        isBusy = busy;
        document.body.classList.toggle("io-busy", busy);
        const statusText = document.getElementById("app-status-text");
        const statusSpinner = document.getElementById("app-status-spinner");
        const statusProgress = document.getElementById("app-status-progress");
        if (busy) {
            if (statusText) statusText.textContent = operation;
            if (statusSpinner) statusSpinner.style.display = "";
            if (statusProgress) statusProgress.style.display = "none";
        } else {
            if (statusText) statusText.textContent = "";
            if (statusSpinner) statusSpinner.style.display = "none";
            if (statusProgress) statusProgress.style.display = "none";
        }
    }

    function showCompletionSummary(title, message) {
        const html = '<div style="text-align:center; max-width:400px;">' +
            '<h2 style="margin-bottom:1rem;">' + title + '</h2>' +
            '<p style="color:var(--text-muted);">' + message + '</p>' +
            '<button onclick="this.closest(\'.io-summary-overlay\').remove()" style="margin-top:1rem; padding:0.5rem 2rem; background:var(--accent); color:#fff; border:none; border-radius:var(--radius-sm); font-weight:600; cursor:pointer; font-family:inherit;">OK</button>' +
            '</div>';
        const overlay = document.createElement("div");
        overlay.className = "io-summary-overlay";
        overlay.style.cssText = 'position:fixed;inset:0;z-index:9999999;background:rgba(0,0,0,0.7);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML = '<div style="background:var(--bg-panel);border:1px solid var(--border);border-radius:var(--radius-lg);padding:1.5rem;max-width:90vw;color:var(--text-main);">' + html + '</div>';
        document.body.appendChild(overlay);
        overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    }

    if (exportBtn) {
        exportBtn.addEventListener("click", async () => {
            if (isBusy) return;
            try {
                setBusy(true, "💾 Подготовка экспорта...");
                if (window.pywebview && window.pywebview.api) {
                    const path = await window.pywebview.api.save_file_dialog(
                        "Экспорт библиотеки",
                        "karaoke_library_" + new Date().toISOString().slice(0, 16).replace(/[T:]/g, "-") + ".zip"
                    );
                    if (!path) { setBusy(false); return; }

                    setBusy(true, "💾 Создание архива...");
                    const res = await fetch("/api/library/export", { method: "POST" });
                    if (!res.ok) throw new Error("Ошибка экспорта");
                    const blob = await res.blob();

                    setBusy(true, "💾 Сохранение файла...");
                    const b64 = await new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onload = () => resolve(reader.result.split(',')[1]);
                        reader.onerror = reject;
                        reader.readAsDataURL(blob);
                    });
                    const ok = await window.pywebview.api.save_binary(path, b64);
                    if (!ok) throw new Error("Не удалось сохранить файл");

                    setBusy(false);
                    showCompletionSummary("📦 Экспорт завершён", "Библиотека успешно сохранена.");
                } else {
                    const res = await fetch("/api/library/export", { method: "POST" });
                    if (!res.ok) throw new Error("Ошибка экспорта");
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "karaoke_library_" + new Date().toISOString().slice(0, 16).replace(/[T:]/g, "-") + ".zip";
                    a.click();
                    URL.revokeObjectURL(url);
                    setBusy(false);
                    showCompletionSummary("📦 Экспорт завершён", "Файл скачан.");
                }
            } catch (e) {
                setBusy(false);
                console.error("Ошибка экспорта:", e);
                showCompletionSummary("❌ Ошибка экспорта", e.message);
            }
        });
    }

    if (importBtn) {
        importBtn.addEventListener("click", async () => {
            if (isBusy) return;
            try {
                if (window.pywebview && window.pywebview.api) {
                    const filePath = await window.pywebview.api.open_file_dialog(false, "ZIP Files | *.zip");
                    if (!filePath) return;
                    setBusy(true, "📦 Импорт библиотеки...");
                    // Python сам читает файл — без передачи base64
                    const res = await fetch("/api/library/import-from-path", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ path: filePath }),
                    });
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        setBusy(false);
                        throw new Error(err.detail || "Ошибка сервера");
                    }
                    const result = await res.json();
                    await loadTracks();
                    setBusy(false);
                    showImportSummary(result);
                } else {
                    // Fallback: HTML input + FormData
                    const input = document.createElement("input");
                    input.type = "file";
                    input.accept = ".zip";
                    input.onchange = async () => {
                        if (input.files.length) await doImport(input.files[0]);
                    };
                    input.click();
                }
            } catch (e) {
                setBusy(false);
                console.error("Ошибка импорта:", e);
                showCompletionSummary("❌ Ошибка импорта", e.message);
            }
        });
    }

    async function doImport(blob, fileName) {
        setBusy(true, "📦 Импорт библиотеки...");
        const fd = new FormData();
        fd.append("file", blob, fileName || "import.zip");

        const res = await fetch("/api/library/import", { method: "POST", body: fd });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            setBusy(false);
            throw new Error(err.detail || "Ошибка сервера");
        }

        const result = await res.json();
        await loadTracks();
        setBusy(false);
        showImportSummary(result);
    }

    function showImportSummary(result) {
        const { added, skipped, errors, artists, tracks } = result;
        const noteIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:1.2em;height:1.2em;vertical-align:-0.15em;display:inline-block;"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>';

        let html = '<div style="text-align:center; max-width:500px; display:flex; flex-direction:column; align-items:center;">';
        html += '<h2 style="margin-bottom:1rem;">📦 Импорт завершён</h2>';

        // Основной контент (без списка треков)
        let mainContent = '';
        if (added > 0) {
            mainContent += '<p style="color:var(--success); font-weight:600; margin:0 0 0.25rem 0;">' + noteIcon + ' Добавлено треков: ' + added + '</p>';
            mainContent += '<p style="font-size:0.85rem; color:var(--text-muted); margin:0 0 0.5rem 0;">Артистов: ' + artists.length + '</p>';
        } else {
            mainContent += '<p style="color:var(--text-muted);">Новых треков не найдено</p>';
        }
        if (skipped > 0) {
            mainContent += '<p style="color:var(--warning); margin:0 0 0.5rem 0;">⏭ Пропущено дубликатов: ' + skipped + '</p>';
        }
        if (errors.length > 0) {
            mainContent += '<details style="margin-top:0.5rem;"><summary style="cursor:pointer; color:var(--danger);">❌ Ошибки (' + errors.length + ')</summary>';
            mainContent += '<ul style="text-align:left; font-size:0.75rem; color:var(--text-muted); padding-left:1.5rem; max-height:100px; overflow-y:auto;">';
            errors.forEach(e => { mainContent += '<li>' + esc(e) + '</li>'; });
            mainContent += '</ul></details>';
        }

        // Список треков — всегда, с прокруткой
        let trackListHtml = '';
        if (tracks.length > 0) {
            trackListHtml = '<ul style="text-align:left; font-size:0.8rem; color:var(--text-muted); padding-left:1.5rem; margin:0.5rem 0 0 0; max-height:180px; overflow-y:auto; width:100%; scrollbar-width:none; -ms-overflow-style:none;">';
            trackListHtml += '<style>.io-summary-overlay .track-scroll::-webkit-scrollbar { display: none !important; width: 0; height: 0; }</style>';
            trackListHtml = trackListHtml.replace('<ul ', '<ul class="track-scroll" ');
            tracks.forEach(t => { trackListHtml += '<li style="margin-bottom:0.15rem;">' + esc(t) + '</li>'; });
            trackListHtml += '</ul>';
        }

        html += '<div style="display:flex; flex-direction:column; align-items:center; max-height:calc(80vh - 120px); overflow:hidden;">';
        html += mainContent;
        html += trackListHtml;
        html += '</div>';
        html += '<button onclick="this.closest(\'.io-summary-overlay\').remove()" style="margin-top:1rem; padding:0.5rem 2rem; background:var(--accent); color:#fff; border:none; border-radius:var(--radius-sm); font-weight:600; cursor:pointer; font-family:inherit;">OK</button>';
        html += '</div>';

        const overlay = document.createElement("div");
        overlay.className = "io-summary-overlay";
        overlay.style.cssText = 'position:fixed;inset:0;z-index:9999999;background:rgba(0,0,0,0.7);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML = '<div style="background:var(--bg-panel);border:1px solid var(--border);border-radius:var(--radius-lg);padding:1.5rem;max-width:90vw;max-height:80vh;overflow:hidden;color:var(--text-main);">' + html + '</div>';
        document.body.appendChild(overlay);
        overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    }

    // Блокировка клавиатуры и кликов во время операции
    document.addEventListener("keydown", (e) => {
        if (!isBusy) return;
        // Разрешаем только Escape для отмены (если будет реализовано)
        if (e.key === "Escape") return;
        e.preventDefault();
        e.stopPropagation();
    }, true);

    document.addEventListener("click", (e) => {
        if (!isBusy) return;
        // Разрешаем клик только по overlay завершения
        if (e.target.closest(".io-summary-overlay")) return;
        e.preventDefault();
        e.stopPropagation();
    }, true);
})();