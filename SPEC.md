# SPEC: Steno (Implemented)

## 1. Scope
This document describes what is currently implemented in the codebase after the UI/architecture refactor.
It is based on:
- current source code under `app.py`, `recorder.py`, `steno/*`;
- implemented parts of earlier planning in previous `SPEC.md`.

## 2. Product Goals (Implemented)
- Record meetings on macOS with separate media tracks:
  - screen + system audio to `.mp4`;
  - microphone audio to `_mic.m4a`.
- Process recordings with Gemini-compatible API and generate `_protocol.txt`.
- Provide a desktop UI to browse recordings, process selected items, and manage artifacts.
- Support first-run permissions onboarding and bilingual UI (RU/EN).

## 3. Current Architecture
- Coordinator:
  - `app.py` (`RecorderApp`) controls app lifecycle, menus, timers, global state.
- Services:
  - `steno/services/permissions_service.py` (`PermissionManager`)
  - `steno/services/recording_service.py` (`RecordingService`)
  - `steno/services/processing_service.py` (`process_video_with_ai`)
  - `steno/services/recordings_service.py` (`RecordingsService`)
- UI:
  - `steno/ui/permissions_window.py`
  - `steno/ui/main_window.py` (selector-safe ObjC class wrapper)
  - `steno/ui/main_window_view.py`
  - `steno/ui/main_window_state.py`
  - `steno/ui/main_window_actions.py`
  - `steno/ui/menu_delegate.py`
- Config/i18n:
  - `steno/config.py`
  - `steno/i18n.py`
  - `assets/i18n/en.yaml`, `assets/i18n/ru.yaml`

## 4. Functional Specification

### 4.1 First Launch and Permissions
- On first launch, app runs one-time TCC reset for:
  - `ScreenCapture`
  - `Microphone`
- State persisted in config:
  - `permissions_reset_done`
  - `permissions_onboarding_done`
- Before onboarding completion, a dedicated permissions window is shown:
  - separate status lines for screen and mic;
  - separate request buttons;
  - transition to main window only after both permissions are granted and both steps were requested.
- On subsequent launches (without reinstall), reset is not repeated.

### 4.2 Main Window
- Two-panel layout:
  - fixed-width sidebar (`300px`);
  - adaptive content area.
- Sidebar contains:
  - Start/Stop button;
  - circular state indicator aligned with button;
  - recordings table;
  - settings button;
  - "Made by Sergey Galay" link.
- Content area contains:
  - selected meeting title;
  - files line (`Video: ...`, `Audio: ...`), video includes `.mp4`;
  - `Process` button;
  - `Copy` protocol button;
  - loader;
  - editable system prompt text area for unprocessed recordings;
  - protocol text view.

### 4.3 Recording Lifecycle
- `Start` validates:
  - onboarding completion;
  - no active processing conflict;
  - API key present;
  - permissions granted.
- Capture files naming:
  - `Meet_DD.MM.YYYY_HH:MM:SS.mp4`
  - `Meet_DD.MM.YYYY_HH:MM:SS_mic.m4a`
- Uses `ScreenRecorder` (`recorder.py`) with dual writers.
- Includes start timeout watchdog (15s) with user alert.
- `Stop` finalizes recording and refreshes UI/menu.

### 4.4 Processing Lifecycle
- Triggered for selected unprocessed recording.
- Uses per-recording prompt draft from UI (falls back to config prompt).
- Uploads `.mp4` and optional `_mic.m4a` to Gemini files API.
- Waits for file readiness; generates protocol with selected model.
- Saves result to `<base>_protocol.txt`.
- Tracks token usage in config:
  - `last_request_tokens`
  - `used_tokens`
- UI status updates:
  - processing state, loader, disabled actions, completion notification.

### 4.5 Recordings List and Statuses
- Source: `save_dir`, `.mp4` only, sorted by mtime desc.
- Status per item:
  - `recording`
  - `processing`
  - `processed`
  - `unprocessed`
- Visual marker in list:
  - blinking marker for actively recording item.

### 4.6 Recording Item Context Menu
Implemented actions (right-click on list item):
- Rename meeting:
  - removes accidental `.mp4` suffix from entered title;
  - renames linked files atomically when present (`.mp4`, `_mic.m4a`, `_protocol.txt`);
  - guards against collisions and rollback on failure.
- Archive:
  - hides recording from list via `hidden_recordings` config;
  - leaves files on disk.
- Delete:
  - removes `.mp4`, `_mic.m4a`, `_protocol.txt` with confirmation.

### 4.7 Protocol Copy
- For processed recordings, protocol can be copied to clipboard via `Copy` button.

### 4.8 Settings
Available in main-window popup and menu settings:
- Video quality
- AI model
- Set API key
- Set Base URL (fallback to default if empty)
- Edit system prompt
- Open output folder
- Token usage display (read-only)

### 4.9 i18n
- Locale auto-detection (NSLocale/env/locale fallback).
- Supported languages:
  - Russian (`ru`)
  - English (`en`)
- All major UI labels/messages are mapped through translation keys.

### 4.10 Menu Bar / Dock Behavior
- App is Dock-visible (`LSUIElement=False`).
- rumps status item is programmatically removed after startup (`hide_status_bar_item`).

## 5. Data Contracts
- Recording entity: `<base>.mp4`
- Optional mic file: `<base>_mic.m4a`
- Optional protocol file: `<base>_protocol.txt`
- Config file: `~/.recorder_app_config.json`

## 6. Non-Functional Requirements (Implemented)
- Long operations are background-threaded (record start callbacks, permission refresh, AI processing).
- UI refresh routed to main thread (`run_on_main`).
- Errors surfaced via alerts/notifications and logs (`~/Library/Logs/Steno/app.log`).

## 7. Build and Packaging
- Entrypoint: `app.py`
- py2app config: `setup.py`
- Data files include icons and i18n YAMLs.
- Python packages included: `steno`, `steno.ui`, `steno.services`.

## 8. Backlog / Not Implemented from Earlier Plan
These plan items are not implemented in current UI:
- sidebar collapse/expand toggle with icon-only mode;
- premium visual polish beyond native controls;
- full removal of legacy permission-reset methods from code (methods exist, but reset options are removed from active settings UI paths).

## 9. Acceptance Snapshot (Current)
Implemented and verified in code:
- first-run explicit permissions flow;
- responsive non-blocking windows;
- recording and processing flows;
- context menu actions for recordings;
- editable per-recording prompt used as final `system_instruction`;
- copy protocol action;
- locale-based RU/EN UI;
- modularized structure (`services`, `ui`, `config`, `i18n`).
