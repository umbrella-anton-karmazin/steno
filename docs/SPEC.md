# SPEC: Steno (As-Built, текущее состояние)

## 1. Назначение документа
Этот документ фиксирует фактически реализованное состояние приложения Steno в текущей кодовой базе.

Источник правды:
- код в `src/steno_app/*`;
- инженерные правила в `AGENTS.md`.

## 2. Продукт и scope
Steno — desktop-приложение для macOS (PyObjC + rumps), которое:
- записывает встречи (экран/системный звук + микрофон);
- обрабатывает запись через Gemini-совместимый API;
- сохраняет протоколы и служебные метаданные;
- управляет списком встреч (rename/archive/delete).

## 3. Архитектура

### 3.1 Координатор
- `src/steno_app/app.py` (`RecorderApp`)
  - lifecycle приложения;
  - status/menu;
  - orchestration сервисов;
  - main-thread dispatch (`run_on_main`).

### 3.2 Сервисы
- `src/steno_app/services/permissions_service.py` (`PermissionManager`)
- `src/steno_app/services/recording_service.py` (`RecordingService`)
- `src/steno_app/services/processing_service.py` (AI pipeline)
- `src/steno_app/services/meetings_service.py` (`MeetingsService`)

Совместимость:
- `src/steno_app/services/recordings_service.py` — shim на `MeetingsService`.

### 3.3 UI
- `src/steno_app/ui/permissions_window.py`
- `src/steno_app/ui/main_window.py` (NSObject + ObjC selectors)
- `src/steno_app/ui/main_window_view.py`
- `src/steno_app/ui/main_window_state.py`
- `src/steno_app/ui/main_window_actions.py`
- `src/steno_app/ui/menu_delegate.py`

### 3.4 Конфиг и локализация
- `src/steno_app/config.py`
- `src/steno_app/i18n.py`
- `src/steno_app/assets/i18n/ru.yaml`
- `src/steno_app/assets/i18n/en.yaml`

## 4. Функциональность

### 4.1 Старт приложения и разрешения
- На старте выполняется preflight наличия прав:
  - Screen Recording
  - Microphone
- Если прав не хватает, открывается отдельное окно выдачи разрешений.
- Если оба доступа есть, открывается основное окно.
- TCC reset при первом запуске не используется.
- Для preflight применяются safe-check с таймаутами (защита от зависаний системных API).

### 4.2 Основное окно
- Двухпанельный layout:
  - sidebar фиксированной ширины;
  - адаптивная контентная область.
- Sidebar:
  - кнопка Start/Stop;
  - список встреч;
  - кнопка Settings.
- Контент:
  - заголовок встречи;
  - информация по файлам (video/audio/duration);
  - блок обработки для необработанных встреч:
    - выбор шаблона промпта;
    - editable `System Prompt`;
    - editable `User Prompt`;
    - кнопка Process;
  - для обработанных встреч:
    - кнопка Copy;
    - рендер протокола (Markdown -> HTML rendering в UI).

### 4.3 Запись
- Запуск записи не зависит от наличия API key.
- Валидации перед стартом:
  - onboarding разрешений завершен;
  - нет конфликтного состояния (`processing`/`waiting permissions`);
  - права экрана/микрофона доступны.
- Имена файлов:
  - видео: `Meet_DD.MM.YYYY_HH:MM:SS.mp4`
  - микрофон: `Meet_DD.MM.YYYY_HH:MM:SS_mic.m4a`
- Есть watchdog таймаута старта (15 сек).

### 4.4 Обработка (AI)
- Обработка запускается для выбранной записи.
- Загружаются:
  - `.mp4`;
  - `_mic.m4a` (если есть).
- Используется комбинация промптов:
  - `system_instruction` (System Prompt);
  - `user prompt` (опционально; пустой допустим).
- Если `user prompt` пустой, он не добавляется в `contents`.
- Результат:
  - `<base>_protocol.txt`
  - `<base>_protocol.meta.json`
- В `.meta.json` сохраняются:
  - `template_id`, `template_name`;
  - `system_prompt`, `user_prompt`;
  - `model_name`, `base_url`;
  - `generated_at`, `source_files`;
  - `usage` token counts;
  - `protocol_variant: "default"` (база под будущие multi-версии).

### 4.5 Шаблоны промптов
- В конфиге есть `prompt_templates`:
  - `templates[]`: `{id, name, system_prompt, user_prompt, built_in, archived}`
  - `selected_template_id`
- Built-in шаблоны:
  - meeting_protocol
  - meeting_transcript
  - meeting_analysis
- Поддерживаются:
  - create/edit/archive/restore/delete (delete только custom);
  - выбор активного шаблона;
  - fallback при удалении/архивировании выбранного custom.
- Архивные шаблоны:
  - не показываются в основном селекте;
  - доступны для восстановления в Settings.

### 4.6 Список встреч и операции
- Источник: `save_dir`, по `.mp4`, сортировка `mtime desc`.
- Контекстное меню встречи:
  - Rename (переименование связанных файлов);
  - Archive (скрыть из списка, файлы оставить);
  - Delete (удалить встречу и связанные файлы).
- Связанные артефакты включают:
  - `.mp4`
  - `_mic.m4a`
  - `_protocol.txt`
  - `_protocol.meta.json`

### 4.7 Копирование протокола
Кнопка Copy поддерживает 2 режима:
- Copy as Markdown (исходный markdown);
- Copy as Text (рендер-представление в plain text, не raw HTML).

### 4.8 Настройки
В настройках доступны:
- Video Quality;
- AI Model;
- Prompt Templates (выбор и управление);
- Set API Key;
- Set Base URL;
- Open Output Folder;
- token usage counters (read-only);
- attribution link.

Пункт `Edit System Prompt` из меню убран.

### 4.9 Локализация (i18n)
- RU и EN поддерживаются через YAML.
- Язык выбирается на основе системной локали.
- Новые ключи для шаблонов и режимов копирования добавлены в обе локали.

## 5. Runtime paths и форматы данных
- Конфиг: `~/.recorder_app_config.json`
- Логи: `~/Library/Logs/Steno/app.log`
- Каталог записей по умолчанию: `~/Movies/Steno`

Соглашения имен:
- video: `<base>.mp4`
- mic: `<base>_mic.m4a`
- protocol: `<base>_protocol.txt`
- protocol metadata: `<base>_protocol.meta.json`

## 6. Нефункциональные свойства
- Долгие операции выполняются в background потоках.
- UI обновляется через main-thread dispatch.
- Добавлены защитные таймауты для permission preflight.
- Ошибки показываются в UI (alert/notification) и пишутся в лог.

## 7. Сборка и запуск

Запуск из исходников:
```bash
PYTHONPATH=src ./.venv/bin/python -m steno_app.app
```

Сборка py2app:
```bash
python3 setup.py py2app
```

## 8. Статус инициативы Prompt Templates
План из `docs/PLAN.md` считается выполненным по решению продукта.

Технически реализовано:
- Эпики 1, 2, 3, 4, 5, 6, 8.
- Из Эпика 7 сознательно оставлен UX-пункт на будущее:
  - упрощение UI промптов (`system prompt` в "Расширенных").

## 9. Backlog (актуальные направления)
- UX-упрощение блока промптов (свернуть `system` в advanced).
- Множественные версии протокола для одной записи (meta foundation уже есть).
- Retry/resume обработки.
- Глобальные hotkeys Start/Stop.
- Экспорт форматов.
- Healthcheck в Settings.
- Безопасное хранение API key (Keychain).
