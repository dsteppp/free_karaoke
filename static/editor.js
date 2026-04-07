// ─────────────────────────────────────────────────────────────────────────────
// editor.js — Интерактивный редактор таймингов AI-Karaoke Pro V8.4
// ─────────────────────────────────────────────────────────────────────────────

(function() {
    // ── Элементы UI ──────────────────────────────────────────────────────────
    const btnStart = document.getElementById("edit-start-btn");
    const btnApply = document.getElementById("edit-apply-btn");
    const btnCancel = document.getElementById("edit-cancel-btn");
    const lyricsDisp = document.getElementById("lyrics-display");
    
    // Создаем Popover-меню "на лету" и добавляем в body
    const popover = document.createElement("div");
    popover.id = "editor-popover";
    popover.innerHTML = `
        <input type="text" id="ep-text" class="ep-input" placeholder="Текст слова">
        <div class="ep-row">
            <button class="ep-btn" id="ep-btn-start">
                <span>⏱ Старт</span>
                <span class="time-val" id="ep-val-start">--:--.--</span>
            </button>
            <button class="ep-btn" id="ep-btn-end">
                <span>⏱ Конец</span>
                <span class="time-val" id="ep-val-end">--:--.--</span>
            </button>
        </div>
        <div class="ep-footer">
            <button class="ep-reset-btn" id="ep-btn-reset">Сбросить якорь</button>
        </div>
    `;
    document.body.appendChild(popover);

    const epText = document.getElementById("ep-text");
    const epBtnStart = document.getElementById("ep-btn-start");
    const epBtnEnd = document.getElementById("ep-btn-end");
    const epValStart = document.getElementById("ep-val-start");
    const epValEnd = document.getElementById("ep-val-end");
    const epBtnReset = document.getElementById("ep-btn-reset");

    // ── Состояние редактора ──────────────────────────────────────────────────
    let isEditMode = false;
    let backupLyricsData = null; // Для отмены изменений
    let currentWordIndex = -1;   // Глобальный индекс редактируемого слова
    let activeTargetSpan = null; // DOM элемент текущего слова для обновления позиции меню

    // ── Утилиты форматирования времени ───────────────────────────────────────
    function formatMs(seconds) {
        if (isNaN(seconds) || seconds < 0) return "--:--.--";
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        const ms = Math.floor((seconds % 1) * 100);
        return `${m}:${s.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`;
    }

    // Синхронизация данных с движком плеера
    function updatePlayerEngineWord(flatIdx, key, value) {
        if (!window.playerLines) return;
        let curr = 0;
        for (let line of window.playerLines) {
            for (let w of line.words) {
                if (curr === flatIdx) {
                    w[key] = parseFloat(value);
                    w.lastPct = "-1"; 
                    return;
                }
                curr++;
            }
        }
    }

    // Обновляет закраску слова мгновенно
    function forceWordRepaint(flatIdx) {
        if (!window.playerLines || !window.instAudio) return;
        const time = window.instAudio.currentTime;
        
        let curr = 0;
        for (let line of window.playerLines) {
            for (let w of line.words) {
                if (curr === flatIdx) {
                    let pct = 0;
                    if (time >= w.end) pct = 100;
                    else if (time > w.start) pct = ((time - w.start) / (w.end - w.start)) * 100;
                    
                    const roundedPct = pct.toFixed(1);
                    w.domNode.style.setProperty("--fill", `${roundedPct}%`);
                    w.lastPct = roundedPct;
                    return;
                }
                curr++;
            }
        }
    }

    // СТРОГОЕ асинхронное восстановление состояния (ждём загрузки новых данных)
    async function reloadTrackAndRestoreTime() {
        if (typeof loadKar !== "function" || !window.currentTrack) return;
        
        const savedTime = window.instAudio.currentTime;
        const t = window.currentTrack;
        const cvr = document.getElementById("cover-img").src;
        
        // Ждем пока скачается новый JSON и полностью отрендерится DOM
        await loadKar(t, cvr);
        
        // Только теперь восстанавливаем время и заставляем плеер перерисовать окружение
        window.instAudio.currentTime = savedTime;
        window.vocAudio.currentTime = savedTime;
        
        const seekEl = document.getElementById("seek-bar");
        if (seekEl) {
            seekEl.value = savedTime;
            seekEl.dispatchEvent(new Event("change"));
        }
    }

    // ── Логика Режима ────────────────────────────────────────────────────────
    function toggleEditMode(enable) {
        if (!window.currentTrack || !window.lyricsData) return;
        isEditMode = enable;

        if (enable) {
            document.body.classList.add("edit-mode");
            window.instAudio.pause();
            window.vocAudio.pause();
            backupLyricsData = JSON.parse(JSON.stringify(window.lyricsData));

            setTimeout(() => {
                const activeLine = document.querySelector(".lyric-line.active-line");
                if (activeLine) {
                    activeLine.scrollIntoView({ block: "center", behavior: "smooth" });
                } else if (lyricsDisp.firstElementChild) {
                    lyricsDisp.firstElementChild.scrollIntoView({ block: "center", behavior: "smooth" });
                }
            }, 50);

        } else {
            document.body.classList.remove("edit-mode", "popover-open");
            popover.classList.remove("visible");
            currentWordIndex = -1;
            activeTargetSpan = null;

            // Сброс скролла при выходе из редактора
            lyricsDisp.scrollTop = 0;

            // Восстанавливаем скролл на активную строку
            setTimeout(() => {
                const activeLine = document.querySelector(".lyric-line.active-line");
                if (activeLine && window.scrollToActiveLine && window.playerLines) {
                    const idx = window.playerLines.findIndex(p => p.domNode === activeLine);
                    if (idx !== -1) window.scrollToActiveLine(idx, "auto");
                }
            }, 50);
        }
    }

    // ── Логика Popover (Меню) ────────────────────────────────────────────────

    // Динамический пересчет позиции меню — с защитой от выхода за края и перекрытия панели
    function updatePopoverPosition() {
        if (!activeTargetSpan || !popover.classList.contains("visible")) return;
        const rect = activeTargetSpan.getBoundingClientRect();

        const popoverW = popover.offsetWidth || 240;
        const popoverH = popover.offsetHeight || 160;
        const margin = 8;
        const panelBottomZone = 100;

        // По умолчанию: popover НАД словом (transform: translate(-50%, -120%))
        let top = rect.top;
        let left = rect.left + (rect.width / 2);

        // Если уходит за верхний край — показываем ПОД словом
        if (top - popoverH * 1.2 < margin) {
            top = rect.bottom + margin;
            popover.style.transform = `translate(-50%, 10px)`;
        } else {
            popover.style.transform = `translate(-50%, -120%)`;
        }

        // Если уходит за нижний край (перекрывает панель) — поднимаем
        if (top + popoverH > window.innerHeight - panelBottomZone) {
            top = rect.top - popoverH - margin;
            if (top < margin) {
                top = rect.bottom + margin;
                popover.style.transform = `translate(-50%, 10px)`;
            } else {
                popover.style.transform = `translate(-50%, -120%)`;
            }
        }

        // Горизонтальное центрирование с защитой от выхода за края
        left = Math.max(margin + popoverW / 2, Math.min(left, window.innerWidth - margin - popoverW / 2));

        popover.style.top = `${top}px`;
        popover.style.left = `${left}px`;
    }

    lyricsDisp.addEventListener("scroll", updatePopoverPosition);
    window.addEventListener("resize", updatePopoverPosition);

    function openPopover(targetSpan, wordData, flatIdx) {
        currentWordIndex = flatIdx;
        activeTargetSpan = targetSpan;
        
        window.instAudio.pause();
        window.vocAudio.pause();

        // Центрируем строку визуально, но НЕ трогаем время аудио-плеера!
        // Плеер остается на той же миллисекунде, где его оставил пользователь.
        const lineElement = targetSpan.closest(".lyric-line");
        if (lineElement) {
            lineElement.scrollIntoView({ block: "center", behavior: "smooth" });
        }

        epText.value = wordData.word;
        epValStart.innerText = formatMs(wordData.start);
        epValEnd.innerText = formatMs(wordData.end);

        epBtnStart.classList.toggle("is-set", !!wordData.is_manual_start);
        epBtnEnd.classList.toggle("is-set", !!wordData.is_manual_end);

        updatePopoverPosition();
        popover.classList.add("visible");
        document.body.classList.add("popover-open");
    }

    function closePopover() {
        popover.classList.remove("visible");
        document.body.classList.remove("popover-open");
        currentWordIndex = -1;
        activeTargetSpan = null;
    }

    // ── Обработчики кликов по словам ─────────────────────────────────────────
    lyricsDisp.addEventListener("click", (e) => {
        if (!isEditMode) return;
        
        const target = e.target.closest(".word");
        if (!target) {
            closePopover(); 
            return;
        }

        const idx = parseInt(target.dataset.index, 10);
        if (isNaN(idx) || !window.lyricsData[idx]) return;

        e.stopPropagation();
        openPopover(target, window.lyricsData[idx], idx);
    });

    // ── Обработчики внутри Popover ───────────────────────────────────────────
    
    epText.addEventListener("input", (e) => {
        if (currentWordIndex === -1) return;
        const w = window.lyricsData[currentWordIndex];
        w.word = e.target.value;
        w.is_manual_text = true;
        
        const span = document.querySelector(`.word[data-index="${currentWordIndex}"]`);
        if (span) {
            span.textContent = w.word;
            span.classList.add("manual-text");
            updatePopoverPosition(); 
        }
    });

    epBtnStart.addEventListener("click", () => {
        if (currentWordIndex === -1) return;
        const w = window.lyricsData[currentWordIndex];
        
        // Берем РЕАЛЬНОЕ время плеера, которое пользователь накрутил ползунком
        const currentTime = window.instAudio.currentTime;

        const originalDuration = Math.max(0.1, w.end - w.start);

        w.start = currentTime;
        w.is_manual_start = true;
        
        if (!w.is_manual_end) {
            w.end = w.start + originalDuration;
        } else if (w.start >= w.end) {
            w.end = w.start + 0.2;
        }

        epValStart.innerText = formatMs(w.start);
        epValEnd.innerText = formatMs(w.end);
        epBtnStart.classList.add("is-set");

        updatePlayerEngineWord(currentWordIndex, "start", w.start);
        updatePlayerEngineWord(currentWordIndex, "end", w.end);
        forceWordRepaint(currentWordIndex);
        
        const span = document.querySelector(`.word[data-index="${currentWordIndex}"]`);
        if (span) span.classList.add("manual-start");
    });

    epBtnEnd.addEventListener("click", () => {
        if (currentWordIndex === -1) return;
        const w = window.lyricsData[currentWordIndex];
        
        // Берем РЕАЛЬНОЕ время плеера
        const currentTime = window.instAudio.currentTime;

        w.end = currentTime;
        w.is_manual_end = true;

        if (w.end <= w.start) {
            w.start = Math.max(0, w.end - 0.2);
            epValStart.innerText = formatMs(w.start);
            updatePlayerEngineWord(currentWordIndex, "start", w.start);
        }

        epValEnd.innerText = formatMs(w.end);
        epBtnEnd.classList.add("is-set");

        updatePlayerEngineWord(currentWordIndex, "end", w.end);
        forceWordRepaint(currentWordIndex);

        const span = document.querySelector(`.word[data-index="${currentWordIndex}"]`);
        if (span) span.classList.add("manual-end");
    });

    epBtnReset.addEventListener("click", () => {
        if (currentWordIndex === -1 || !backupLyricsData) return;
        
        const orig = backupLyricsData[currentWordIndex];
        const w = window.lyricsData[currentWordIndex];
        
        w.start = orig.start;
        w.end = orig.end;
        w.word = orig.word;
        w.is_manual_start = false;
        w.is_manual_end = false;
        w.is_manual_text = false;

        epText.value = w.word;
        epValStart.innerText = formatMs(w.start);
        epValEnd.innerText = formatMs(w.end);
        epBtnStart.classList.remove("is-set");
        epBtnEnd.classList.remove("is-set");

        updatePlayerEngineWord(currentWordIndex, "start", w.start);
        updatePlayerEngineWord(currentWordIndex, "end", w.end);
        forceWordRepaint(currentWordIndex);

        const span = document.querySelector(`.word[data-index="${currentWordIndex}"]`);
        if (span) {
            span.textContent = w.word;
            span.classList.remove("manual-start", "manual-end", "manual-text");
            updatePopoverPosition();
        }
    });

    popover.addEventListener("click", e => e.stopPropagation());

    // ── Кнопки основной панели ───────────────────────────────────────────────
    
    btnStart.addEventListener("click", () => toggleEditMode(true));
    
    btnCancel.addEventListener("click", async () => {
        window.lyricsData = backupLyricsData;
        toggleEditMode(false);
        await reloadTrackAndRestoreTime();
    });

    // Escape: закрывает popover или выходит из редактора
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            if (popover.classList.contains("visible")) {
                closePopover();
            } else if (isEditMode) {
                window.lyricsData = backupLyricsData;
                toggleEditMode(false);
            }
        }
    });

    btnApply.addEventListener("click", async () => {
        if (!window.currentTrack || !window.lyricsData) return;

        const trackId = window.currentTrack.id;
        const payload = { words: window.lyricsData };

        btnApply.innerHTML = "⏳ Сохранение...";
        btnApply.style.pointerEvents = "none";

        try {
            const res = await fetch(`/api/tracks/${trackId}/edit_lyrics`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "Ошибка сервера");
            }

            toggleEditMode(false);
            await reloadTrackAndRestoreTime();

        } catch (e) {
            alert("Ошибка при сохранении: " + e.message);
        } finally {
            btnApply.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>Применить`;
            btnApply.style.pointerEvents = "auto";
        }
    });

})();