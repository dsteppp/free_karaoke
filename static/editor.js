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

    // Перезагрузка трека с сохранением позиции ползунка времени
    function reloadTrackAndRestoreTime() {
        if (typeof loadKar !== "function" || !window.currentTrack) return;
        
        const savedTime = window.instAudio.currentTime;
        const t = window.currentTrack;
        const cvr = document.getElementById("cover-img").src;
        
        // Запускаем стандартную загрузку трека
        loadKar(t, cvr);
        
        // Ожидаем загрузки метаданных нового аудио, чтобы применить сохраненное время
        const restoreHandler = () => {
            window.instAudio.currentTime = savedTime;
            window.vocAudio.currentTime = savedTime;
            
            // Искусственно вызываем событие change для ползунка, чтобы плеер отрендерил нужную строку
            const seekEl = document.getElementById("seek-bar");
            if (seekEl) {
                seekEl.value = savedTime;
                seekEl.dispatchEvent(new Event("change"));
            }
            
            // Удаляем обработчик, чтобы он сработал только один раз
            window.instAudio.removeEventListener("loadedmetadata", restoreHandler);
        };
        
        window.instAudio.addEventListener("loadedmetadata", restoreHandler);
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
        } else {
            document.body.classList.remove("edit-mode", "popover-open");
            popover.classList.remove("visible");
            currentWordIndex = -1;
            activeTargetSpan = null;
        }
    }

    // ── Логика Popover (Меню) ────────────────────────────────────────────────
    
    // Динамический пересчет позиции меню
    function updatePopoverPosition() {
        if (!activeTargetSpan || !popover.classList.contains("visible")) return;
        const rect = activeTargetSpan.getBoundingClientRect();
        
        // Позиция: по центру слова, чуть выше него
        let top = rect.top - 10;
        let left = rect.left + (rect.width / 2);

        popover.style.top = `${top}px`;
        popover.style.left = `${left}px`;
    }

    // Привязываем пересчет позиции к скроллу и ресайзу, чтобы меню не отрывалось
    lyricsDisp.addEventListener("scroll", updatePopoverPosition);
    window.addEventListener("resize", updatePopoverPosition);

    function openPopover(targetSpan, wordData, flatIdx) {
        currentWordIndex = flatIdx;
        activeTargetSpan = targetSpan;
        
        // Ставим на паузу при клике
        window.instAudio.pause();
        window.vocAudio.pause();

        // Центрируем строку на экране
        const lineElement = targetSpan.closest(".lyric-line");
        if (lineElement) {
            lineElement.scrollIntoView({ block: "center", behavior: "smooth" });
        }

        // Заполняем данные меню
        epText.value = wordData.word;
        epValStart.innerText = formatMs(wordData.start);
        epValEnd.innerText = formatMs(wordData.end);

        epBtnStart.classList.toggle("is-set", !!wordData.is_manual_start);
        epBtnEnd.classList.toggle("is-set", !!wordData.is_manual_end);

        // Позиционируем меню
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
            // Поскольку длина текста изменилась, пересчитываем позицию меню
            updatePopoverPosition(); 
        }
    });

    epBtnStart.addEventListener("click", () => {
        if (currentWordIndex === -1) return;
        const w = window.lyricsData[currentWordIndex];
        const currentTime = window.instAudio.currentTime;

        // Вычисляем оригинальную длительность слова (но не менее 0.1с)
        const originalDuration = Math.max(0.1, w.end - w.start);

        w.start = currentTime;
        w.is_manual_start = true;
        
        // ВАЖНО: Сдвигаем конец слова, чтобы сохранить его физическую длительность,
        // если пользователь не фиксировал конец вручную.
        if (!w.is_manual_end) {
            w.end = w.start + originalDuration;
        } else if (w.start >= w.end) {
            w.end = w.start + 0.2; // Экстренный фикс парадокса
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
    
    btnCancel.addEventListener("click", () => {
        window.lyricsData = backupLyricsData;
        toggleEditMode(false);
        reloadTrackAndRestoreTime();
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
            reloadTrackAndRestoreTime();

        } catch (e) {
            alert("Ошибка при сохранении: " + e.message);
        } finally {
            btnApply.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>Применить`;
            btnApply.style.pointerEvents = "auto";
        }
    });

})();