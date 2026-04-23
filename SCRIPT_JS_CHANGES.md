# 📝 Изменения в script.js: Экспорт/Импорт с polling-архитектурой

## ✅ Реализованные функции

### 1. **Глобальное состояние для I/O операций**
```javascript
let currentIoTaskId = null;        // ID текущей задачи Huey
let currentIoOperation = null;     // 'export' или 'import'
```

### 2. **Новая функция `updateAppStatusFromTask(status)`**
Обновляет строку состояния из ответа задачи:
- `status.message` → текст операции
- `status.progress` → ширина прогресс-бара (0-100%)
- Автоматически переключает спиннер/прогресс-бар

### 3. **Функция `startExport()`** (строки 1495-1578)
**Алгоритм:**
1. Диалог сохранения через `pywebview.api.save_file_dialog()`
2. POST `/api/library/export` с `{output_path: path}` → получает `task_id`
3. Polling каждые 1 сек: GET `/api/library/export/status/{task_id}`
4. Обработка статусов:
   - `"running"` → обновление прогресса через `updateAppStatusFromTask()`
   - `"done"` → завершение, показ уведомления
   - `"error"`/`"cancelled"` → очистка состояния, показ ошибки
   - `"not_found"` → ошибка

**Fallback для браузера:** старый метод с blob (не для больших файлов)

### 4. **Функция `startImport()`** (строки 1582-1662)
**Алгоритм:**
1. Диалог выбора файла через `pywebview.api.open_file_dialog()`
2. POST `/api/library/import` с `{path: filePath}` → получает `task_id`
3. Polling каждые 1 сек: GET `/api/library/import/status/{task_id}`
4. После `"done"` → вызов `loadTracks()` + показ сводки импорта

**Fallback для браузера:** HTML input + FormData

### 5. **Функция `cancelCurrentOperation()`** (строки 1666-1685)
- Проверяет наличие активной задачи
- Отправляет POST на `/api/library/{export|import}/cancel/{task_id}`
- Обновляет строку состояния на "⏹ Отмена..."

### 6. **Кнопка отмены** (строки 1688-1692)
```javascript
const cancelIoBtn = document.getElementById("cancel-io-btn");
if (cancelIoBtn) {
    cancelIoBtn.addEventListener("click", cancelCurrentOperation);
}
```

**Примечание:** Кнопка должна существовать в HTML. Если её нет — код не падает.

### 7. **Обновлённая функция `setBusy()`** (строки 1434-1455)
- Добавлена поддержка прогресс-бара (`statusProgressFill.style.width`)
- Инициализирует ширину прогресса в 0% при старте

## 🔑 Ключевые отличия от старой версии

| Аспект | Было | Стало |
|--------|------|-------|
| **Экспорт** | Загрузка всего ZIP в blob → save_binary | Polling задачи, Python пишет напрямую на диск |
| **Импорт** | FormData → bytes → extractall() | Передача пути → Python читает потоково |
| **Прогресс** | Только "загрузка..." | Точный % + имя текущего файла |
| **Отмена** | ❌ Нет | ✅ Кнопка + эндпоинт отмены |
| **RAM** | ~размер архива (50-100 ГБ) | ~50-100 МБ (буфер ZIP) |

## 🧩 Интеграция с бэкендом

### Ожидаемые эндпоинты:
```
POST   /api/library/export              → {task_id}
GET    /api/library/export/status/:id   → {status, message?, progress?}
POST   /api/library/export/cancel/:id   → {status: "cancelling"}

POST   /api/library/import              → {task_id}
GET    /api/library/import/status/:id   → {status, message?, progress?}
POST   /api/library/import/cancel/:id   → {status: "cancelling"}
```

### Формат ответа статуса:
```json
{
  "task_id": "...",
  "status": "running" | "done" | "error" | "cancelled" | "not_found",
  "message": "💾 Экспорт: track_001.mp3 (150/1000)",  // опционально
  "progress": 15,                                      // опционально (0-100)
  "result": {...}                                      // только для "done"
}
```

## 🎨 UI требования

### Необходимые элементы в HTML:
```html
<!-- Кнопка отмены (опционально, но рекомендуется) -->
<button id="cancel-io-btn">Отменить</button>

<!-- Прогресс-бар в строке состояния -->
<div id="app-status-progress">
  <div id="app-status-progress-fill"></div>
</div>
```

### CSS классы:
```css
.io-busy { /* Блокировка интерфейса */ }
.io-summary-overlay { /* Модальное окно завершения */ }
```

## 🧪 Тестирование

### Сценарии для проверки:
1. ✅ Экспорт библиотеки 1000+ файлов → мониторинг RAM
2. ✅ Импорт архива 50+ ГБ → проверка прогресса
3. ✅ Отмена экспорта на 50% → файл должен остаться валидным ZIP
4. ✅ Fallback в браузере (без pywebview) → малые файлы
5. ✅ Обработка ошибок сервера → понятное сообщение пользователю

## 📊 Метрики после внедрения

| Метрика | Значение |
|---------|----------|
| Размер файла | 1787 строк (+151 к оригиналу) |
| Новые функции | 5 (startExport, startImport, cancelCurrentOperation, updateAppStatusFromTask, doImport) |
| Глобальные переменные | 2 (currentIoTaskId, currentIoOperation) |
| Поддержка отмены | ✅ Да |
| Progress polling | ✅ Да (1 сек интервал) |
| Fallback для браузера | ✅ Да |

## ⚠️ Важные замечания

1. **Кнопка отмены опциональна** — если `#cancel-io-btn` отсутствует, код работает без неё
2. **Fallback режим** — для браузеров без pywebview используется старый метод (blob)
3. **Интервал polling** — 1 секунда (баланс между точностью и нагрузкой)
4. **Очистка состояния** — `currentIoTaskId` и `currentIoOperation` сбрасываются после завершения/ошибки
