# app.py
import rumps
import subprocess
import os
import signal
import json
import threading
import time
import re
import sys
import locale as py_locale
import certifi
import shutil
import logging
from datetime import datetime
from google import genai
from google.genai import types

# --- Custom Recorder Import ---
# Убедись, что recorder.py лежит рядом и обновлен (версия с двумя райтерами)
from recorder import ScreenRecorder

messageAuthor = 'v1.3'
APP_BUNDLE_ID = "com.sergeygalay.steno"

# --- macOS Permission & Native Capture Imports ---
try:
    import objc
    from AVFoundation import (
        AVCaptureDevice, AVMediaTypeAudio, AVAuthorizationStatusAuthorized,
        AVCaptureSession, AVCaptureScreenInput, AVCaptureDeviceInput,
        AVCaptureMovieFileOutput, AVCaptureVideoOrientationLandscapeLeft
    )
    from Quartz import (
        CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess,
        CGMainDisplayID
    )
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    from UserNotifications import UNUserNotificationCenter, UNAuthorizationOptionAlert, UNAuthorizationOptionSound, UNAuthorizationOptionBadge
    from AppKit import (
        NSMenu, NSMenuItem, NSWindow, NSButton, NSTextField, NSFont, NSView,
        NSScrollView, NSTableView, NSTableColumn, NSTextView, NSStatusBar,
        NSProgressIndicator, NSBezelStyleRounded,
        NSPasteboard, NSPasteboardTypeString,
        NSAlert, NSAlertStyleWarning,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
        NSBackingStoreBuffered, NSApp, NSVisualEffectView,
        NSVisualEffectMaterialSidebar, NSVisualEffectStateActive,
        NSVisualEffectBlendingModeBehindWindow, NSColor, NSViewWidthSizable,
        NSViewHeightSizable, NSViewMinXMargin, NSViewMaxYMargin,
        NSViewMinYMargin, NSViewMaxXMargin
    )
    from Foundation import NSObject, NSURL, NSRunLoop, NSDate, NSBundle, NSIndexSet, NSThread, NSLocale
    from PyObjCTools import AppHelper
    HAS_PYOBJC = True
except ImportError as e:
    print(f"PyObjC import error: {e}")
    HAS_PYOBJC = False
except Exception as e:
    print(f"Unexpected error during PyObjC imports: {e}")
    HAS_PYOBJC = False

# --- Настройка логирования ---
LOG_DIR = os.path.expanduser("~/Library/Logs/Steno")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
LOG_FILE = os.path.join(LOG_DIR, "app.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)
logger = logging.getLogger("Steno")

# --- SSL Configuration ---
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

# --- Константы и Настройки ---
CONFIG_FILE = os.path.expanduser("~/.recorder_app_config.json")

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_PATH, "assets")

ICON_IDLE = os.path.join(ASSETS_DIR, "icon_idle.png")
ICON_RECORDING = os.path.join(ASSETS_DIR, "icon_recording.png")
ICON_PROCESSING = os.path.join(ASSETS_DIR, "icon_processing.png")
ICON_ERROR = os.path.join(ASSETS_DIR, "icon_error.png")

AI_MODELS = [
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-flash-lite-latest"
]

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://gemini-warmup.galaypro.ru",
    "video_device_idx": "0",
    "video_device_name": "Main Screen",
    "model_name": "gemini-3-flash-preview",
    "prompt": "Ты — ИИ-ассистент для составления протоколов встреч. Твоя задача — проанализировать предоставленный медиафайл и вернуть ТОЛЬКО протокол в формате Markdown (оптимизированный для Confluence), строго без вступительных слов, приветствий и пояснений самой нейросети.\n\nИспользуй следующий шаблон:\n# Протокол встречи: [Сформулируй тему]\n**Дата:** [Дата из запроса]\n**Участники:** [Список имен или ролей]\n\n## 1. Саммари (Summary)\n[Краткое, структурированное содержание обсуждения без воды]\n\n## 2. Принятые решения\n* [Список конкретных решений]\n\n## 3. План действий (Action Items)\nОформи строго как таблицу:\n| Задача | Ответственный | Срок |\n| :--- | :--- | :--- |\n| [Описание задачи] | [Имя] | [Дедлайн или -] |",
    "save_dir": os.path.expanduser("~/Movies/Steno"),
    "video_quality": "Medium",
    "used_tokens": 0,
    "last_request_tokens": 0,
    "permissions_reset_done": False,
    "permissions_onboarding_done": False,
    "hidden_recordings": []
}

VIDEO_QUALITY_PRESETS = {
    "Low": {"width": 960, "height": 540, "fps": 5, "bitrate": 1000000},
    "Medium": {"width": 1280, "height": 720, "fps": 10, "bitrate": 3000000},
    "Medium_Q_low_FPS": {"width": 1280, "height": 720, "fps": 1, "bitrate": 3000000},
    "High": {"width": 1920, "height": 1080, "fps": 30, "bitrate": 8000000},
    "High_Q_low_FPS": {"width": 1920, "height": 1080, "fps": 1, "bitrate": 8000000},
    "Ultra": {"width": 2560, "height": 1440, "fps": 60, "bitrate": 25000000}
}

I18N_DIR = os.path.join(ASSETS_DIR, "i18n")


def _parse_flat_yaml(path):
    data = {}
    if not os.path.exists(path):
        return data

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue

            if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                value = value[1:-1]
                value = value.replace("\\n", "\n").replace("\\t", "\t")
                value = value.replace('\\"', '"').replace("\\\\", "\\")
            elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
                value = value[1:-1].replace("''", "'")
            else:
                if " #" in value:
                    value = value.split(" #", 1)[0].rstrip()
            data[key] = value
    return data


def _detect_system_language():
    candidates = []

    if HAS_PYOBJC:
        try:
            languages = NSLocale.preferredLanguages()
            if languages:
                candidates.append(str(languages[0]))
        except Exception:
            pass

    for env_name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)

    try:
        loc = py_locale.getlocale()[0]
        if loc:
            candidates.append(loc)
    except Exception:
        pass

    for candidate in candidates:
        normalized = str(candidate).strip().lower()
        if normalized.startswith("ru"):
            return "ru"
        if normalized.startswith("en"):
            return "en"
    return "en"


class Localizer:
    def __init__(self, i18n_dir):
        self.i18n_dir = i18n_dir
        self.lang = _detect_system_language()
        self.fallback = _parse_flat_yaml(os.path.join(self.i18n_dir, "en.yaml"))
        self.active = _parse_flat_yaml(os.path.join(self.i18n_dir, f"{self.lang}.yaml"))

    def translate(self, key, **kwargs):
        text = self.active.get(key, self.fallback.get(key, key))
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text


LOCALIZER = Localizer(I18N_DIR)


def tr(key, **kwargs):
    return LOCALIZER.translate(key, **kwargs)

# --- Утилиты ---
def get_meeting_date(filename):
    """
    Алгоритм получения даты встречи:
    1. Из названия файла (Meet_YYYY-MM-DD_HH-MM-SS.mp4)
    2. Дата изменения файла
    3. Дата создания файла
    4. Текущая дата
    """
    # 1. Попытка распарсить из имени файла
    # Ожидаемый формат от рекордера: Meet_DD.MM.YYYY_HH:MM:SS.mp4
    basename = os.path.basename(filename)
    match = re.search(r"Meet_(\d{2}\.\d{2}\.\d{4})_", basename)
    if match:
        return match.group(1)
    
    # 2. Дата изменения
    try:
        mtime = os.path.getmtime(filename)
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    except:
        pass

    # 3. Дата создания
    try:
        ctime = os.path.getctime(filename)
        return datetime.fromtimestamp(ctime).strftime("%Y-%m-%d")
    except:
        pass

    # 4. Текущая дата
    return datetime.now().strftime("%Y-%m-%d")

class PermissionManager:
    @staticmethod
    def is_mic_authorized():
        if not HAS_PYOBJC:
            return False
        return AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio) == AVAuthorizationStatusAuthorized

    @staticmethod
    def is_screen_authorized():
        if not HAS_PYOBJC:
            return False
        return bool(CGPreflightScreenCaptureAccess())

    @staticmethod
    def _request_screen_access_blocking():
        try:
            granted = CGRequestScreenCaptureAccess()
            logger.info(f"Screen capture permission granted: {granted}")
            return bool(granted)
        except Exception as e:
            logger.warning(f"Screen capture permission request failed: {e}")
            return False

    @staticmethod
    def check_all():
        if not HAS_PYOBJC:
            return
        logger.info("Checking system permissions...")
        
        mic_status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        if mic_status != AVAuthorizationStatusAuthorized:
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, lambda granted: logger.info(f"Mic permission granted: {granted}"))

        if not CGPreflightScreenCaptureAccess():
            # CGRequestScreenCaptureAccess can block until the user responds.
            # Run it outside UI/main thread to avoid app freeze.
            threading.Thread(
                target=PermissionManager._request_screen_access_blocking,
                daemon=True
            ).start()

        center = UNUserNotificationCenter.currentNotificationCenter()
        options = UNAuthorizationOptionAlert | UNAuthorizationOptionSound | UNAuthorizationOptionBadge
        center.requestAuthorizationWithOptions_completionHandler_(options, lambda granted, error: logger.info(f"Notifications permission granted: {granted}"))

class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    return {**DEFAULT_CONFIG, **json.load(f)}
            except: pass
        return DEFAULT_CONFIG.copy()

    @staticmethod
    def save(config):
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)

# --- Воркер ИИ (ОБНОВЛЕННЫЙ ПОД ДВА ФАЙЛА) ---
def process_video_with_ai(video_path, config, app_instance, prompt_override=None):
    try:
        app_instance.is_processing = True
        app_instance.request_set_state_icon("processing")
        logger.info(f"Starting AI processing logic for: {video_path}")
        
        api_key = config.get("api_key")
        if not api_key:
            logger.error("API Key is missing")
            rumps.notification(
                tr("ai.error.title"),
                tr("ai.error.missing_api_key"),
                tr("ai.error.configure_api_key")
            )
            app_instance.is_processing = False
            if app_instance.is_recording:
                app_instance.request_set_state_icon("recording")
            else:
                app_instance.request_set_state_icon("idle")
            return

        # 1. Определяем файлы для загрузки
        # Основное видео + микрофон (MP4)
        files_to_upload_paths = [video_path]
        
        # Ищем файл микрофона (M4A)
        # Он должен лежать рядом с именем: имя_файла_mic.m4a
        base_name = os.path.splitext(video_path)[0]
        mic_audio_path = base_name + "_mic.m4a"
        
        if os.path.exists(mic_audio_path):
            logger.info(f"Found microphone audio track: {mic_audio_path}")
            files_to_upload_paths.append(mic_audio_path)
        else:
            logger.warning("Microphone audio file not found, processing video only.")

        # 2. Инициализация клиента
        client_kwargs = {"api_key": api_key}
        base_url = config.get("base_url", "").strip()
        if base_url:
            if not base_url.startswith(("http://", "https://")):
                base_url = "https://" + base_url
            client_kwargs["http_options"] = {"baseUrl": base_url}
        
        client = genai.Client(**client_kwargs)

        rumps.notification(
            tr("ai.processing.title"),
            tr("ai.processing.uploading"),
            tr("ai.processing.files_count", count=len(files_to_upload_paths))
        )
        
        # 3. Загрузка всех файлов
        uploaded_files = []
        try:
            for path in files_to_upload_paths:
                logger.info(f"Uploading {os.path.basename(path)}...")
                uf = client.files.upload(file=path)
                uploaded_files.append(uf)
        except Exception as upload_err:
            logger.exception("File upload failed")
            raise Exception(f"Ошибка загрузки: {upload_err}")

        # 4. Ожидание процессинга ВСЕХ файлов
        ready_files = []
        for uf in uploaded_files:
            logger.info(f"Waiting for processing: {uf.name} ({uf.display_name})")
            while uf.state.name == "PROCESSING":
                time.sleep(3)
                uf = client.files.get(name=uf.name)

            if uf.state.name == "FAILED":
                logger.error(f"Google failed to process file {uf.name}")
                raise Exception(f"Google не смог обработать файл {uf.display_name}")
            
            ready_files.append(uf)
            logger.info(f"File ready: {uf.name}")
        
        # 5. Генерация контента
        logger.info(f"Generating protocol with model: {config.get('model_name')}")

        # Формируем жесткий User Prompt с датой
        meeting_date = get_meeting_date(video_path)
        user_prompt_text = f"Составь протокол по прикрепленному файлу.\n\nДата встречи: {meeting_date}"
        
        # Системный промпт: берем итоговый текст из UI (если передан), иначе из конфига.
        system_instruction = (prompt_override or config.get("prompt", "")).strip() or config.get("prompt", "")

        # Собираем контент: [File1, File2, ..., UserPrompt]
        contents = ready_files + [user_prompt_text]

        response = client.models.generate_content(
            model=config.get("model_name"),
            contents=contents,
            config=types.GenerateContentConfig(
                http_options={"timeout": 600000},
                system_instruction=system_instruction
            )
        )

        # --- Token Usage Tracking ---
        if response.usage_metadata:
            total_tokens = response.usage_metadata.total_token_count
            config["used_tokens"] = config.get("used_tokens", 0) + total_tokens
            config["last_request_tokens"] = total_tokens
            ConfigManager.save(config)
            try:
                app_instance.run_on_main(app_instance.update_token_stats)
            except Exception as e:
                logger.warning(f"Failed to update token stats in UI: {e}")
        # ----------------------------

        txt_path = base_name + "_protocol.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(response.text)

        logger.info(f"Protocol saved to: {txt_path}")

        # 6. Удаление файлов из облака
        for uf in ready_files:
            try: 
                client.files.delete(name=uf.name)
                logger.info(f"Remote file deleted: {uf.name}")
            except Exception as delete_err: 
                logger.warning(f"Could not delete remote file: {delete_err}")

        rumps.notification(
            tr("ai.done.title"),
            tr("ai.done.protocol_saved"),
            tr("ai.done.file_name", filename=os.path.basename(txt_path))
        )
        app_instance.is_processing = False
        app_instance.current_processing_file = None
        app_instance.request_ui_refresh()
        
        if app_instance.is_recording:
            app_instance.request_set_state_icon("recording")
        else:
            app_instance.request_set_state_icon("idle")

    except Exception as e:
        logger.exception("AI worker failed")
        rumps.notification(tr("ai.error.title"), tr("ai.error.processing_failed"), str(e)[:50])
        app_instance.request_flash_error()
        app_instance.is_processing = False
        app_instance.current_processing_file = None
        app_instance.request_ui_refresh()
        if app_instance.is_recording:
            app_instance.request_set_state_icon("recording")
        else:
            app_instance.request_set_state_icon("idle")

if HAS_PYOBJC:
    class PermissionWindowController(NSObject):
        def initWithApp_(self, app):
            self = objc.super(PermissionWindowController, self).init()
            if self:
                self.app = app
                self.screen_requested = False
                self.mic_requested = False
                self.screen_granted = False
                self.mic_granted = False
                self.bootstrap_done = bool(self.app.config.get("permissions_reset_done", False))
                self.build_window()
            return self

        @objc.python_method
        def _label(self, frame, text, bold=False, secondary=False):
            label = NSTextField.alloc().initWithFrame_(frame)
            label.setBezeled_(False)
            label.setDrawsBackground_(False)
            label.setEditable_(False)
            label.setSelectable_(False)
            label.setStringValue_(text)
            if bold:
                label.setFont_(NSFont.boldSystemFontOfSize_(14.0))
            elif secondary:
                label.setFont_(NSFont.systemFontOfSize_(12.0))
                label.setTextColor_(NSColor.secondaryLabelColor())
            return label

        @objc.python_method
        def _button(self, frame, title, action):
            button = NSButton.alloc().initWithFrame_(frame)
            button.setTitle_(title)
            button.setTarget_(self)
            button.setAction_(action)
            button.setBezelStyle_(NSBezelStyleRounded)
            return button

        @objc.python_method
        def build_window(self):
            style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                ((280.0, 180.0), (760.0, 420.0)),
                style,
                NSBackingStoreBuffered,
                False
            )
            self.window.setDelegate_(self)
            self.window.setTitle_(tr("permissions.window_title"))
            self.window.setMinSize_((720.0, 400.0))
            self.window.setMovableByWindowBackground_(False)

            root = self.window.contentView()

            title = self._label(((24.0, 360.0), (710.0, 26.0)), tr("permissions.title"), bold=True)
            title.setFont_(NSFont.boldSystemFontOfSize_(22.0))
            root.addSubview_(title)

            desc = self._label(
                ((24.0, 328.0), (710.0, 24.0)),
                tr("permissions.description"),
                secondary=True
            )
            root.addSubview_(desc)

            self.screen_status = self._label(
                ((24.0, 248.0), (500.0, 28.0)),
                tr("permissions.screen_status", status=tr("permissions.status.unknown")),
                bold=True
            )
            root.addSubview_(self.screen_status)
            self.screen_button = self._button(
                ((540.0, 244.0), (190.0, 34.0)),
                tr("permissions.request_screen"),
                "onRequestScreen:"
            )
            root.addSubview_(self.screen_button)

            self.mic_status = self._label(
                ((24.0, 180.0), (500.0, 28.0)),
                tr("permissions.mic_status", status=tr("permissions.status.unknown")),
                bold=True
            )
            root.addSubview_(self.mic_status)
            self.mic_button = self._button(
                ((540.0, 176.0), (190.0, 34.0)),
                tr("permissions.request_mic"),
                "onRequestMic:"
            )
            root.addSubview_(self.mic_button)

            self.hint_label = self._label(
                ((24.0, 70.0), (710.0, 70.0)),
                tr("permissions.hint"),
                secondary=True
            )
            root.addSubview_(self.hint_label)

            self.refresh_statuses()

        @objc.python_method
        def set_bootstrap_state(self, done, text):
            self.bootstrap_done = bool(done)
            self.hint_label.setStringValue_(text)
            self.refresh_statuses()

        def windowWillClose_(self, _):
            rumps.quit_application()

        @objc.python_method
        def show_window(self):
            self.window.makeKeyAndOrderFront_(None)
            app = NSApp()
            if app:
                app.activateIgnoringOtherApps_(True)

        @objc.python_method
        def close_window(self):
            self.window.orderOut_(None)

        @objc.python_method
        def refresh_statuses(self):
            def check_permissions_worker():
                screen_granted = PermissionManager.is_screen_authorized()
                mic_granted = PermissionManager.is_mic_authorized()
                self.app.run_on_main(self._apply_permission_statuses, screen_granted, mic_granted)

            threading.Thread(target=check_permissions_worker, daemon=True).start()

        @objc.python_method
        def _apply_permission_statuses(self, screen_granted, mic_granted):
            self.screen_granted = bool(screen_granted)
            self.mic_granted = bool(mic_granted)

            # If permissions are already granted (e.g., manually in System Settings),
            # treat the corresponding step as completed.
            if self.screen_granted:
                self.screen_requested = True
            if self.mic_granted:
                self.mic_requested = True

            screen_status_key = "permissions.status.granted" if self.screen_granted else "permissions.status.not_granted"
            self.screen_status.setStringValue_(
                tr("permissions.screen_status", status=tr(screen_status_key))
            )
            self.screen_status.setTextColor_(NSColor.systemGreenColor() if self.screen_granted else NSColor.systemRedColor())
            mic_status_key = "permissions.status.granted" if self.mic_granted else "permissions.status.not_granted"
            self.mic_status.setStringValue_(
                tr("permissions.mic_status", status=tr(mic_status_key))
            )
            self.mic_status.setTextColor_(NSColor.systemGreenColor() if self.mic_granted else NSColor.systemRedColor())

            self.screen_button.setEnabled_(self.bootstrap_done and (not self.screen_granted))
            self.mic_button.setEnabled_(self.bootstrap_done and (not self.mic_granted))

            if self.bootstrap_done and self.screen_requested and self.mic_requested and self.screen_granted and self.mic_granted:
                self.app.request_complete_permissions_onboarding()

        def onRequestScreen_(self, _):
            self.screen_requested = True
            self.screen_button.setEnabled_(False)

            def request_and_refresh():
                PermissionManager._request_screen_access_blocking()
                self.app.run_on_main(self.refresh_statuses)

            threading.Thread(target=request_and_refresh, daemon=True).start()

        def onRequestMic_(self, _):
            self.mic_requested = True

            def completion(granted):
                logger.info(f"Mic permission granted from onboarding: {granted}")
                self.app.run_on_main(self.refresh_statuses)

            AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, completion)
            self.refresh_statuses()

    class MainWindowController(NSObject):
        def initWithApp_(self, app):
            self = objc.super(MainWindowController, self).init()
            if self:
                self.app = app
                self.recording_files = []
                self.selected_recording = None
                self.prompt_drafts = {}
                self.prompt_loaded_for = None
                self.build_window()
            return self

        @objc.python_method
        def _label(self, frame, text, bold=False, secondary=False):
            label = NSTextField.alloc().initWithFrame_(frame)
            label.setBezeled_(False)
            label.setDrawsBackground_(False)
            label.setEditable_(False)
            label.setSelectable_(False)
            label.setStringValue_(text)
            if bold:
                label.setFont_(NSFont.boldSystemFontOfSize_(13.0))
            elif secondary:
                label.setFont_(NSFont.systemFontOfSize_(12.0))
                label.setTextColor_(NSColor.secondaryLabelColor())
            return label

        @objc.python_method
        def _button(self, frame, title, action, bordered=True):
            button = NSButton.alloc().initWithFrame_(frame)
            button.setTitle_(title)
            button.setTarget_(self)
            button.setAction_(action)
            button.setBordered_(bordered)
            if bordered:
                button.setBezelStyle_(NSBezelStyleRounded)
            return button

        @objc.python_method
        def build_window(self):
            style = (
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskMiniaturizable
                | NSWindowStyleMaskResizable
            )
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                ((220.0, 120.0), (1120.0, 760.0)),
                style,
                NSBackingStoreBuffered,
                False
            )
            self.window.setDelegate_(self)
            self.window.setTitle_(tr("main.window_title"))
            self.window.setMinSize_((920.0, 560.0))
            self.window.setMovableByWindowBackground_(False)

            root = self.window.contentView()
            self.sidebar_width = 300.0
            self.sidebar_view = NSView.alloc().initWithFrame_(((0.0, 0.0), (self.sidebar_width, root.bounds()[1][1])))
            self.sidebar_view.setAutoresizingMask_(NSViewHeightSizable | NSViewMaxXMargin)
            self.sidebar_view.setWantsLayer_(True)
            self.sidebar_view.layer().setBackgroundColor_(NSColor.windowBackgroundColor().CGColor())
            root.addSubview_(self.sidebar_view)

            self.content_view = NSView.alloc().initWithFrame_(((self.sidebar_width, 0.0), (root.bounds()[1][0] - self.sidebar_width, root.bounds()[1][1])))
            self.content_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            self.content_view.setWantsLayer_(True)
            self.content_view.layer().setBackgroundColor_(NSColor.textBackgroundColor().CGColor())
            root.addSubview_(self.content_view)

            self.start_stop_button = self._button(
                ((16.0, self.sidebar_view.bounds()[1][1] - 46.0), (210.0, 32.0)),
                tr("main.start_recording"),
                "onStartStop:"
            )
            self.start_stop_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
            self.sidebar_view.addSubview_(self.start_stop_button)

            start_button_frame = self.start_stop_button.frame()
            dot_size = 18.0
            dot_x = start_button_frame.origin.x + start_button_frame.size.width + 12.0
            dot_y = start_button_frame.origin.y + ((start_button_frame.size.height - dot_size) / 2.0)
            self.recording_dot_view = NSView.alloc().initWithFrame_(((dot_x, dot_y), (dot_size, dot_size)))
            self.recording_dot_view.setAutoresizingMask_(NSViewMinXMargin | NSViewMinYMargin)
            self.recording_dot_view.setWantsLayer_(True)
            self.recording_dot_view.layer().setCornerRadius_(dot_size / 2.0)
            self.recording_dot_view.setHidden_(True)
            self.sidebar_view.addSubview_(self.recording_dot_view)

            list_top = self.sidebar_view.bounds()[1][1] - 72.0
            list_bottom = 88.0
            self.recordings_scroll = NSScrollView.alloc().initWithFrame_(((8.0, list_bottom), (284.0, max(100.0, list_top - list_bottom))))
            self.recordings_scroll.setHasVerticalScroller_(True)
            self.recordings_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

            self.recordings_table = NSTableView.alloc().initWithFrame_(((0.0, 0.0), (284.0, max(100.0, list_top - list_bottom))))
            self.recordings_table.setDelegate_(self)
            self.recordings_table.setDataSource_(self)
            self.recordings_table.setHeaderView_(None)
            self.recordings_table.setUsesAlternatingRowBackgroundColors_(False)
            self.recordings_table.setSelectionHighlightStyle_(0)
            self.recordings_table.setFocusRingType_(1)
            column = NSTableColumn.alloc().initWithIdentifier_("recording")
            column.setWidth_(280.0)
            try:
                column.dataCell().setEditable_(False)
            except Exception:
                pass
            self.recordings_table.addTableColumn_(column)
            self.recordings_scroll.setDocumentView_(self.recordings_table)
            self.sidebar_view.addSubview_(self.recordings_scroll)
            self._build_recordings_context_menu()

            self.settings_button = self._button(((14.0, 30.0), (40.0, 40.0)), "☰", "onOpenSettings:", bordered=False)
            self.settings_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMaxYMargin)
            self.settings_button.setFont_(NSFont.systemFontOfSize_(18.0))
            try:
                self.settings_button.setWantsLayer_(True)
                self.settings_button.layer().setCornerRadius_(10.0)
                self.settings_button.layer().setBackgroundColor_(NSColor.quaternaryLabelColor().colorWithAlphaComponent_(0.2).CGColor())
            except Exception:
                pass
            self.sidebar_view.addSubview_(self.settings_button)

            self.made_by_link = self._button(
                ((62.0, 40.0), (220.0, 22.0)),
                tr("main.made_by"),
                "onOpenLink:",
                bordered=False
            )
            self.made_by_link.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
            self.made_by_link.setContentTintColor_(NSColor.systemBlueColor())
            self.sidebar_view.addSubview_(self.made_by_link)

            self.detail_title_label = self._label(
                ((24.0, self.content_view.bounds()[1][1] - 52.0), (760.0, 28.0)),
                tr("main.select_recording"),
                bold=True
            )
            self.detail_title_label.setFont_(NSFont.boldSystemFontOfSize_(20.0))
            self.detail_title_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
            self.content_view.addSubview_(self.detail_title_label)

            self.files_label = self._label(
                ((24.0, self.content_view.bounds()[1][1] - 118.0), (820.0, 54.0)),
                tr("main.files_default"),
                secondary=True
            )
            self.files_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
            self.content_view.addSubview_(self.files_label)

            self.process_button = self._button(
                ((24.0, self.content_view.bounds()[1][1] - 160.0), (120.0, 30.0)),
                tr("main.process"),
                "onProcessSelected:"
            )
            self.process_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
            self.content_view.addSubview_(self.process_button)

            self.copy_protocol_button = self._button(
                ((156.0, self.content_view.bounds()[1][1] - 160.0), (140.0, 30.0)),
                tr("main.copy"),
                "onCopyProtocol:"
            )
            self.copy_protocol_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
            self.content_view.addSubview_(self.copy_protocol_button)

            self.loader = NSProgressIndicator.alloc().initWithFrame_(((308.0, self.content_view.bounds()[1][1] - 160.0), (24.0, 24.0)))
            self.loader.setStyle_(0)
            self.loader.setDisplayedWhenStopped_(False)
            self.loader.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
            self.content_view.addSubview_(self.loader)

            self.prompt_label = self._label(
                ((24.0, self.content_view.bounds()[1][1] - 200.0), (260.0, 24.0)),
                tr("main.system_prompt_editable"),
                bold=True
            )
            self.prompt_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
            self.content_view.addSubview_(self.prompt_label)

            self.prompt_scroll = NSScrollView.alloc().initWithFrame_(((24.0, self.content_view.bounds()[1][1] - 334.0), (self.content_view.bounds()[1][0] - 48.0, 120.0)))
            self.prompt_scroll.setHasVerticalScroller_(True)
            self.prompt_scroll.setHasHorizontalScroller_(False)
            self.prompt_scroll.setBorderType_(2)
            self.prompt_scroll.setDrawsBackground_(True)
            self.prompt_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
            try:
                self.prompt_scroll.setWantsLayer_(True)
                self.prompt_scroll.layer().setCornerRadius_(6.0)
                self.prompt_scroll.layer().setBorderWidth_(1.0)
                self.prompt_scroll.layer().setBorderColor_(NSColor.quaternaryLabelColor().CGColor())
            except Exception:
                pass
            self.prompt_text = NSTextView.alloc().initWithFrame_(self.prompt_scroll.bounds())
            self.prompt_text.setEditable_(True)
            self.prompt_text.setSelectable_(True)
            self.prompt_text.setRichText_(False)
            self.prompt_text.setFont_(NSFont.systemFontOfSize_(12.0))
            self.prompt_text.setDrawsBackground_(True)
            self.prompt_text.setBackgroundColor_(NSColor.textBackgroundColor())
            self.prompt_scroll.setDocumentView_(self.prompt_text)
            self.content_view.addSubview_(self.prompt_scroll)

            self.prompt_hint_label = self._label(
                ((24.0, self.content_view.bounds()[1][1] - 356.0), (700.0, 18.0)),
                tr("main.prompt_hint"),
                secondary=True
            )
            self.prompt_hint_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
            self.content_view.addSubview_(self.prompt_hint_label)

            self.protocol_scroll = NSScrollView.alloc().initWithFrame_(((24.0, 24.0), (self.content_view.bounds()[1][0] - 48.0, self.content_view.bounds()[1][1] - 396.0)))
            self.protocol_scroll.setHasVerticalScroller_(True)
            self.protocol_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            self.protocol_text = NSTextView.alloc().initWithFrame_(self.protocol_scroll.bounds())
            self.protocol_text.setEditable_(False)
            self.protocol_text.setSelectable_(True)
            self.protocol_text.setRichText_(False)
            self.protocol_text.setFont_(NSFont.systemFontOfSize_(13.0))
            self.protocol_scroll.setDocumentView_(self.protocol_text)
            self.content_view.addSubview_(self.protocol_scroll)

            self._layout_root_views()
            self.refresh_all()

        @objc.python_method
        def _layout_root_views(self):
            root = self.window.contentView()
            root_width, root_height = root.bounds()[1]
            content_width = max(320.0, root_width - self.sidebar_width)
            self.sidebar_view.setFrame_(((0.0, 0.0), (self.sidebar_width, root_height)))
            self.content_view.setFrame_(((self.sidebar_width, 0.0), (content_width, root_height)))

        @objc.python_method
        def _build_recordings_context_menu(self):
            self.recordings_context_menu = NSMenu.alloc().initWithTitle_(tr("main.recording_context_title"))
            self.recordings_context_menu.setAutoenablesItems_(False)
            self.recordings_context_menu.setDelegate_(self)

            self.ctx_rename_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.ctx_rename"), "onContextRename:", "")
            self.ctx_rename_item.setTarget_(self)
            self.recordings_context_menu.addItem_(self.ctx_rename_item)

            self.ctx_archive_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.ctx_archive"), "onContextArchive:", "")
            self.ctx_archive_item.setTarget_(self)
            self.recordings_context_menu.addItem_(self.ctx_archive_item)

            self.recordings_context_menu.addItem_(NSMenuItem.separatorItem())

            self.ctx_delete_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.ctx_delete"), "onContextDelete:", "")
            self.ctx_delete_item.setTarget_(self)
            self.recordings_context_menu.addItem_(self.ctx_delete_item)

            self.recordings_table.setMenu_(self.recordings_context_menu)

        @objc.python_method
        def _update_recordings_context_menu_state(self):
            has_selected = bool(self.selected_recording and self.selected_recording in self.recording_files)
            status = self._status_for_recording(self.selected_recording) if has_selected else "none"
            can_modify = has_selected and status not in ("recording", "processing")
            self.ctx_rename_item.setEnabled_(can_modify)
            self.ctx_archive_item.setEnabled_(can_modify)
            self.ctx_delete_item.setEnabled_(can_modify)

        def windowDidResize_(self, _):
            self._layout_root_views()

        def windowWillClose_(self, _):
            rumps.quit_application()

        @objc.python_method
        def show_window(self):
            self.window.makeKeyAndOrderFront_(None)
            app = NSApp()
            if app:
                app.activateIgnoringOtherApps_(True)

        @objc.python_method
        def refresh_all(self):
            self.refresh_from_state()
            self.refresh_file_lists()
            self.refresh_detail_view()

        @objc.python_method
        def _current_prompt_text(self):
            try:
                return str(self.prompt_text.string())
            except Exception:
                return self.app.config.get("prompt", "")

        @objc.python_method
        def _remember_prompt_draft_for_selected(self):
            if not self.selected_recording:
                return
            # Save only when prompt editor is actually loaded for this row.
            # Prevents writing empty draft during initial auto-selection.
            if self.prompt_loaded_for != self.selected_recording:
                return
            if self._status_for_recording(self.selected_recording) != "unprocessed":
                return
            self.prompt_drafts[self.selected_recording] = self._current_prompt_text()

        @objc.python_method
        def _is_recording_file(self, filename):
            if not filename or not self.app.current_filename:
                return False
            return (
                self.app.is_recording and
                os.path.basename(self.app.current_filename) == filename
            )

        @objc.python_method
        def _status_for_recording(self, filename):
            if not filename:
                return "none"
            if self._is_recording_file(filename):
                return "recording"
            if self.app.current_processing_file == filename:
                return "processing"
            base = os.path.splitext(filename)[0]
            protocol_path = os.path.join(self.app.config["save_dir"], base + "_protocol.txt")
            return "processed" if os.path.exists(protocol_path) else "unprocessed"

        @objc.python_method
        def _display_meeting_name(self, filename):
            if not filename:
                return ""
            if filename.lower().endswith(".mp4"):
                return os.path.splitext(filename)[0]
            return filename

        @objc.python_method
        def _display_title_for_recording(self, filename):
            status = self._status_for_recording(filename)
            recording_prefix = "●" if self.app.recording_blink_on else "○"
            prefix = {
                "recording": recording_prefix,
                "processed": "✓",
                "processing": "…",
                "unprocessed": "○"
            }.get(status, " ")
            return f"{prefix}  {self._display_meeting_name(filename)}"

        @objc.python_method
        def refresh_from_state(self):
            if self.app.is_recording:
                self.recording_dot_view.layer().setBackgroundColor_(NSColor.systemRedColor().CGColor())
                self.recording_dot_view.setHidden_(False)
                self.start_stop_button.setTitle_(tr("main.stop_recording"))
            elif self.app.is_waiting_permissions:
                self.recording_dot_view.layer().setBackgroundColor_(NSColor.systemOrangeColor().CGColor())
                self.recording_dot_view.setHidden_(False)
                self.start_stop_button.setTitle_(tr("main.starting"))
            elif self.app.is_processing:
                self.recording_dot_view.layer().setBackgroundColor_(NSColor.systemOrangeColor().CGColor())
                self.recording_dot_view.setHidden_(False)
                self.start_stop_button.setTitle_(tr("main.start_recording"))
            else:
                self.recording_dot_view.setHidden_(True)
                self.start_stop_button.setTitle_(tr("main.start_recording"))

            self.start_stop_button.setEnabled_(
                (not self.app.is_processing or self.app.is_recording)
                and not self.app.is_waiting_permissions
            )

        @objc.python_method
        def refresh_file_lists(self):
            self.recording_files = self.app.list_recent_recordings(limit=200)
            if self.app.current_filename:
                active_name = os.path.basename(self.app.current_filename)
                if active_name and active_name not in self.recording_files:
                    self.recording_files.insert(0, active_name)
            if self.selected_recording not in self.recording_files:
                self.selected_recording = self.recording_files[0] if self.recording_files else None

            self.recordings_table.reloadData()
            if self.selected_recording in self.recording_files:
                idx = self.recording_files.index(self.selected_recording)
                self.recordings_table.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(idx), False)
            self._update_recordings_context_menu_state()

        @objc.python_method
        def refresh_detail_view(self):
            if not self.selected_recording:
                self.detail_title_label.setStringValue_(tr("main.select_recording"))
                self.files_label.setStringValue_(tr("main.files_default"))
                self.process_button.setHidden_(True)
                self.copy_protocol_button.setHidden_(True)
                self.prompt_label.setHidden_(True)
                self.prompt_scroll.setHidden_(True)
                self.prompt_hint_label.setHidden_(True)
                self.prompt_loaded_for = None
                self.loader.stopAnimation_(None)
                self.protocol_text.setString_(tr("main.select_recording_hint"))
                return

            video_name = self.selected_recording
            base = os.path.splitext(video_name)[0]
            mic_name = base + "_mic.m4a"
            mic_path = os.path.join(self.app.config["save_dir"], mic_name)
            protocol_path = os.path.join(self.app.config["save_dir"], base + "_protocol.txt")
            status = self._status_for_recording(video_name)
            has_protocol = os.path.exists(protocol_path)

            display_name = self._display_meeting_name(video_name)
            self.detail_title_label.setStringValue_(display_name)
            audio_label = mic_name if os.path.exists(mic_path) else tr("main.audio_missing")
            self.files_label.setStringValue_(tr("main.files_line", video=video_name, audio=audio_label))

            if status == "processing":
                self.process_button.setHidden_(False)
                self.process_button.setEnabled_(False)
                self.copy_protocol_button.setHidden_(True)
                self.prompt_label.setHidden_(True)
                self.prompt_scroll.setHidden_(True)
                self.prompt_hint_label.setHidden_(True)
                self.loader.startAnimation_(None)
            elif status == "unprocessed":
                self.process_button.setHidden_(False)
                self.process_button.setEnabled_(not self.app.is_processing and not self.app.is_recording)
                self.copy_protocol_button.setHidden_(True)
                self.prompt_label.setHidden_(False)
                self.prompt_scroll.setHidden_(False)
                self.prompt_hint_label.setHidden_(False)
                if self.prompt_loaded_for != video_name:
                    prompt_value = self.prompt_drafts.get(video_name)
                    if prompt_value is None:
                        prompt_value = self.app.config.get("prompt", "")
                    self.prompt_text.setString_(prompt_value)
                    self.prompt_loaded_for = video_name
                self.loader.stopAnimation_(None)
            elif status == "recording":
                self.process_button.setHidden_(True)
                self.copy_protocol_button.setHidden_(True)
                self.prompt_label.setHidden_(True)
                self.prompt_scroll.setHidden_(True)
                self.prompt_hint_label.setHidden_(True)
                self.loader.stopAnimation_(None)
            else:
                self.process_button.setHidden_(True)
                self.copy_protocol_button.setHidden_(False)
                self.copy_protocol_button.setEnabled_(has_protocol)
                self.prompt_label.setHidden_(True)
                self.prompt_scroll.setHidden_(True)
                self.prompt_hint_label.setHidden_(True)
                self.loader.stopAnimation_(None)

            if os.path.exists(protocol_path):
                try:
                    with open(protocol_path, "r", encoding="utf-8") as f:
                        self.protocol_text.setString_(f.read())
                except Exception as e:
                    self.protocol_text.setString_(tr("main.protocol_read_error", error=e))
            elif status == "processing":
                self.protocol_text.setString_(tr("main.processing_in_progress"))
            else:
                self.protocol_text.setString_(tr("main.no_protocol"))

        def onStartStop_(self, _):
            self.app.record_switch(None)
            self.refresh_from_state()
            self.refresh_file_lists()
            self.refresh_detail_view()

        def onProcessSelected_(self, _):
            if not self.selected_recording:
                return
            if self._status_for_recording(self.selected_recording) != "unprocessed":
                return
            self._remember_prompt_draft_for_selected()
            final_prompt = self.prompt_drafts.get(self.selected_recording, self.app.config.get("prompt", ""))
            self.app.process_video_file(self.selected_recording, prompt_override=final_prompt)
            self.refresh_from_state()
            self.refresh_file_lists()
            self.refresh_detail_view()

        def onCopyProtocol_(self, _):
            if not self.selected_recording:
                return
            base = os.path.splitext(self.selected_recording)[0]
            protocol_path = os.path.join(self.app.config["save_dir"], base + "_protocol.txt")
            if not os.path.exists(protocol_path):
                rumps.alert(tr("copy.title"), tr("copy.not_ready"))
                return
            try:
                with open(protocol_path, "r", encoding="utf-8") as f:
                    text = f.read()
                pasteboard = NSPasteboard.generalPasteboard()
                pasteboard.clearContents()
                pasteboard.setString_forType_(text, NSPasteboardTypeString)
                rumps.notification(
                    tr("copy.success_title"),
                    tr("copy.success_body"),
                    os.path.basename(protocol_path)
                )
            except Exception as e:
                rumps.alert(tr("copy.error_title"), str(e))

        def onContextRename_(self, _):
            if not self.selected_recording:
                return
            old_name = self.selected_recording
            self._remember_prompt_draft_for_selected()
            renamed_to = self.app.rename_recording_interactive(old_name)
            if renamed_to:
                old_draft = self.prompt_drafts.pop(old_name, None)
                if old_draft is not None:
                    self.prompt_drafts[renamed_to] = old_draft
                self.selected_recording = renamed_to
                self.prompt_loaded_for = None
            self.refresh_from_state()
            self.refresh_file_lists()
            self.refresh_detail_view()

        def onContextArchive_(self, _):
            if not self.selected_recording:
                return
            target = self.selected_recording
            if self.app.archive_recording_interactive(target):
                self.prompt_drafts.pop(target, None)
                if self.prompt_loaded_for == target:
                    self.prompt_loaded_for = None
                if self.selected_recording == target:
                    self.selected_recording = None
            self.refresh_from_state()
            self.refresh_file_lists()
            self.refresh_detail_view()

        def onContextDelete_(self, _):
            if not self.selected_recording:
                return
            target = self.selected_recording
            if self.app.delete_recording_with_files_interactive(target):
                self.prompt_drafts.pop(target, None)
                if self.prompt_loaded_for == target:
                    self.prompt_loaded_for = None
                if self.selected_recording == target:
                    self.selected_recording = None
            self.refresh_from_state()
            self.refresh_file_lists()
            self.refresh_detail_view()

        def onOpenSettings_(self, sender):
            menu = NSMenu.alloc().initWithTitle_(tr("main.settings_title"))

            quality_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.video_quality"), None, "")
            quality_submenu = NSMenu.alloc().initWithTitle_(tr("main.video_quality"))
            for q_name in VIDEO_QUALITY_PRESETS.keys():
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(q_name, "onSelectQuality:", "")
                item.setTarget_(self)
                item.setRepresentedObject_(q_name)
                item.setState_(1 if q_name == self.app.config.get("video_quality", "Medium") else 0)
                quality_submenu.addItem_(item)
            quality_item.setSubmenu_(quality_submenu)
            menu.addItem_(quality_item)

            model_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.ai_model"), None, "")
            model_submenu = NSMenu.alloc().initWithTitle_(tr("main.ai_model"))
            for model_name in AI_MODELS:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(model_name, "onSelectModel:", "")
                item.setTarget_(self)
                item.setRepresentedObject_(model_name)
                item.setState_(1 if model_name == self.app.config.get("model_name") else 0)
                model_submenu.addItem_(item)
            model_item.setSubmenu_(model_submenu)
            menu.addItem_(model_item)

            menu.addItem_(NSMenuItem.separatorItem())
            for title, action in [
                (tr("main.set_api_key"), "onSetApiKey:"),
                (tr("main.set_base_url"), "onSetBaseURL:"),
                (tr("main.edit_system_prompt"), "onEditPrompt:"),
                (tr("main.open_output_folder"), "onOpenOutput:")
            ]:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
                item.setTarget_(self)
                menu.addItem_(item)

            menu.addItem_(NSMenuItem.separatorItem())
            usage_last = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                tr("menu.tokens_last", value=self.app.config.get("last_request_tokens", 0)),
                None,
                ""
            )
            usage_last.setEnabled_(False)
            usage_total = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                tr("menu.tokens_used", value=self.app.config.get("used_tokens", 0)),
                None,
                ""
            )
            usage_total.setEnabled_(False)
            menu.addItem_(usage_last)
            menu.addItem_(usage_total)

            NSMenu.popUpContextMenu_withEvent_forView_(menu, NSApp().currentEvent(), sender)

        def onSelectQuality_(self, sender):
            self.app.set_video_quality_value(str(sender.representedObject()))

        def onSelectModel_(self, sender):
            self.app.set_ai_model_value(str(sender.representedObject()))

        def onSetApiKey_(self, _):
            self.app.set_api_key(None)

        def onSetBaseURL_(self, _):
            self.app.set_base_url(None)

        def onEditPrompt_(self, _):
            self.app.edit_prompt(None)

        def onOpenOutput_(self, _):
            self.app.open_folder(None)

        def onResetPermissions_(self, _):
            self.app.reset_permissions(None)

        def onResetPermissionsRestart_(self, _):
            self.app.reset_permissions_and_restart(None)

        def onOpenLink_(self, _):
            self.app.open_link(None)

        def menuWillOpen_(self, menu):
            if menu != getattr(self, "recordings_context_menu", None):
                return
            event = NSApp().currentEvent()
            if event:
                try:
                    point = self.recordings_table.convertPoint_fromView_(event.locationInWindow(), None)
                    row = self.recordings_table.rowAtPoint_(point)
                    if 0 <= row < len(self.recording_files):
                        if self.recording_files[row] != self.selected_recording:
                            self._remember_prompt_draft_for_selected()
                        self.recordings_table.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(row), False)
                    else:
                        self.ctx_rename_item.setEnabled_(False)
                        self.ctx_archive_item.setEnabled_(False)
                        self.ctx_delete_item.setEnabled_(False)
                        return
                except Exception:
                    pass
            self._update_recordings_context_menu_state()

        def numberOfRowsInTableView_(self, _):
            return len(self.recording_files)

        def tableView_objectValueForTableColumn_row_(self, _, __, row):
            if row < 0 or row >= len(self.recording_files):
                return ""
            return self._display_title_for_recording(self.recording_files[row])

        def tableView_shouldEditTableColumn_row_(self, _, __, ___):
            return False

        def tableViewSelectionDidChange_(self, _):
            row = self.recordings_table.selectedRow()
            if row < 0 or row >= len(self.recording_files):
                self._update_recordings_context_menu_state()
                return
            self._remember_prompt_draft_for_selected()
            self.selected_recording = self.recording_files[row]
            self.prompt_loaded_for = None
            self.refresh_detail_view()
            self._update_recordings_context_menu_state()

class RecorderApp(rumps.App):
    def __init__(self):
        initial_icon = ICON_IDLE if os.path.exists(ICON_IDLE) else None
        title = tr("status.short") if initial_icon is None else ""
        
        super(RecorderApp, self).__init__(name=title, icon=initial_icon, quit_button=None)
        self.config = ConfigManager.load()
        self.is_recording = False
        self.recording_blink_on = True
        self.is_processing = False
        self.is_waiting_permissions = False
        self.start_attempt_id = 0
        self.current_processing_file = None
        self.status_item_hidden = False
        self.permissions_transition_started = False
        self.permission_controller = None
        self.window_controller = None
        
        # Native Capture Properties
        self.recorder = None
        self.current_filename = None
        self.mic_audio_filename = None
        
        if not os.path.exists(self.config["save_dir"]):
            os.makedirs(self.config["save_dir"])

        self.recent_recordings_menu = rumps.MenuItem(tr("menu.recent_recordings"))
        self.recent_protocols_menu = rumps.MenuItem(tr("menu.recent_protocols"))
        self.build_menu()
        self.refresh_files_menus()
        
        if HAS_PYOBJC:
            self._delegate = MenuDelegate.alloc().initWithApp_(self)
            self._menu._menu.setDelegate_(self._delegate)
            # Start UI flow once runloop is alive.
            try:
                AppHelper.callAfter(self._start_initial_ui_flow)
            except Exception:
                logger.exception("Failed to schedule initial UI flow")

        logger.info("Steno initialized (Dual-Stream Mode)")

    def _reset_permissions_first_launch_if_needed(self):
        if self.config.get("permissions_reset_done", False):
            return

        logger.info("First launch detected. Scheduling one-time TCC permission reset.")

        def worker():
            for service in ("ScreenCapture", "Microphone"):
                try:
                    result = subprocess.run(
                        ["tccutil", "reset", service, APP_BUNDLE_ID],
                        capture_output=True,
                        text=True,
                        timeout=8
                    )
                    if result.returncode != 0:
                        details = (result.stderr or result.stdout or "Unknown error").strip()
                        logger.warning(f"Permission reset failed for {service}: {details}")
                except subprocess.TimeoutExpired:
                    logger.warning(f"Permission reset timed out for {service}")
                except Exception as e:
                    logger.warning(f"Permission reset exception for {service}: {e}")

            self.config["permissions_reset_done"] = True
            ConfigManager.save(self.config)

            def on_done():
                if self.permission_controller:
                    self.permission_controller.set_bootstrap_state(
                        True,
                        tr("permissions.bootstrap_done")
                    )
            self.run_on_main(on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _start_initial_ui_flow(self):
        if self.config.get("permissions_onboarding_done", False):
            self.ensure_main_window()
        else:
            self.show_permissions_window()
            if not self.config.get("permissions_reset_done", False):
                if self.permission_controller:
                    self.permission_controller.set_bootstrap_state(
                        False,
                        tr("permissions.bootstrap_in_progress")
                    )
                self._reset_permissions_first_launch_if_needed()

    def ensure_main_window(self):
        if not self.window_controller:
            self.window_controller = MainWindowController.alloc().initWithApp_(self)
        self.window_controller.show_window()

    def show_permissions_window(self):
        if self.config.get("permissions_onboarding_done", False):
            self.ensure_main_window()
            return
        if not self.permission_controller:
            self.permission_controller = PermissionWindowController.alloc().initWithApp_(self)
        self.permission_controller.show_window()

    def request_complete_permissions_onboarding(self):
        self.run_on_main(self.complete_permissions_onboarding)

    def complete_permissions_onboarding(self):
        if self.permissions_transition_started:
            return
        if self.config.get("permissions_onboarding_done", False):
            self.ensure_main_window()
            return

        self.permissions_transition_started = True
        logger.info("Completing permissions onboarding and opening main UI")
        self.config["permissions_onboarding_done"] = True
        try:
            ConfigManager.save(self.config)
            if self.permission_controller:
                self.permission_controller.close_window()
                self.permission_controller = None
            self.ensure_main_window()
        except Exception:
            logger.exception("Failed to complete permissions onboarding")
            self.permissions_transition_started = False

    @rumps.timer(30)
    def auto_refresh_menu(self, _):
        if HAS_PYOBJC and not self.config.get("permissions_onboarding_done", False):
            return
        if not self.is_recording:
            self.refresh_files_menus()

    @rumps.timer(1)
    def hide_status_bar_item(self, _):
        if self.status_item_hidden:
            return
        try:
            if hasattr(self, "_nsapp") and hasattr(self._nsapp, "nsstatusitem"):
                NSStatusBar.systemStatusBar().removeStatusItem_(self._nsapp.nsstatusitem)
                self.status_item_hidden = True
        except Exception:
            pass

    def set_state_icon(self, state):
        icons = {
            "idle": (ICON_IDLE, tr("status.short")),
            "recording": (ICON_RECORDING, tr("status.recording")),
            "processing": (ICON_PROCESSING, tr("status.processing")),
            "awaiting_permission": (ICON_PROCESSING, tr("status.awaiting_permission")),
            "error": (ICON_ERROR, tr("status.error"))
        }
        path, text = icons.get(state, (None, tr("status.short")))
        if path and os.path.exists(path):
            self.icon = path
            self.title = ""
        else:
            self.icon = None
            self.title = text
            
        # Trigger UI update whenever icon/state changes context
        self.update_ui_state()

    @rumps.timer(0.5)
    def update_ui_state(self, _=None):
        """
        Updates the enabled/disabled state of menu items based on current app state.
        Runs periodically on the main thread to ensure UI safety.
        
        Rules:
        1. If Processing (is_processing=True):
           - Disable "Recent Recordings" (prevent parallel AI)
           - Disable "Start Recording" (prevent recording during AI) -> BUT allow "Stop" if recording.
           
        2. If Recording (is_recording=True):
           - Disable "Recent Recordings" (prevent AI during recording)
           - "Start Recording" becomes "Stop" and must remain enabled.
        """
        if not HAS_PYOBJC:
            return
        if not self.config.get("permissions_onboarding_done", False):
            # Keep onboarding mode lightweight and avoid extra UI churn.
            return

        # Determine states
        # Can we start a new recording? Only if not recording AND not processing
        can_start_new_recording = (
            not self.is_recording
            and not self.is_processing
            and not self.is_waiting_permissions
        )
        
        # Can we stop? Only if recording
        can_stop = self.is_recording
        
        # Can we use Recent Recordings? Only if IDLE (not recording AND not processing)
        can_use_recent = not (self.is_recording or self.is_processing or self.is_waiting_permissions)

        # Blink marker for actively recording item in the list.
        if self.is_recording:
            self.recording_blink_on = not self.recording_blink_on
        else:
            self.recording_blink_on = True

        # 1. Update Recent Recordings Menu
        if hasattr(self, 'recent_recordings_menu') and hasattr(self.recent_recordings_menu, '_menuitem'):
            try:
                self.recent_recordings_menu._menuitem.setEnabled_(can_use_recent)
            except Exception:
                pass

        # 2. Update Start/Stop menu item
        if hasattr(self, "start_stop_item") and hasattr(self.start_stop_item, "_menuitem"):
            try:
                self.start_stop_item._menuitem.setEnabled_(can_stop or can_start_new_recording)
            except Exception:
                pass

        if self.window_controller:
            self.window_controller.refresh_from_state()
            if self.is_recording or self.current_processing_file:
                self.window_controller.refresh_file_lists()

    def flash_error(self):
        def blink():
            for _ in range(6):
                self.run_on_main(self.set_state_icon, "error")
                time.sleep(0.5)
                self.run_on_main(self.set_state_icon, "idle")
                time.sleep(0.5)
        threading.Thread(target=blink, daemon=True).start()

    def build_menu(self):
        self.model_menu = rumps.MenuItem(tr("menu.ai_model"))
        for model in AI_MODELS:
            item = rumps.MenuItem(model, callback=self.select_ai_model)
            if model == self.config["model_name"]: item.state = 1
            self.model_menu.add(item)

        self.open_ui_item = rumps.MenuItem(tr("menu.open_ui"), callback=self.open_main_window)
        self.start_stop_item = rumps.MenuItem(tr("menu.start_recording"), callback=self.record_switch)
        self.settings_menu = rumps.MenuItem(tr("menu.settings"))
        self.open_output_item = rumps.MenuItem(tr("menu.open_output_folder"), callback=self.open_folder)
        self.made_by_item = rumps.MenuItem(tr("menu.made_by"), callback=self.open_link)
        self.quit_item = rumps.MenuItem(tr("menu.quit"), callback=rumps.quit_application)

        self.menu = [
            self.open_ui_item,
            None,
            self.start_stop_item,
            self.recent_recordings_menu,
            self.recent_protocols_menu,
            None,
            self.settings_menu,
            self.open_output_item,
            None,
            self.made_by_item,
            self.quit_item
        ]

        # Video Quality Menu
        self.quality_menu = rumps.MenuItem(tr("menu.video_quality"))
        for q_name in VIDEO_QUALITY_PRESETS.keys():
            item = rumps.MenuItem(q_name, callback=self.select_video_quality)
            if q_name == self.config.get("video_quality", "Medium"):
                item.state = 1
            self.quality_menu.add(item)

        self.settings_menu.add(self.quality_menu)
        self.settings_menu.add(self.model_menu)
        self.settings_menu.add(rumps.MenuItem(tr("menu.edit_system_prompt"), callback=self.edit_prompt))
        self.settings_menu.add(rumps.MenuItem(tr("menu.set_api_key"), callback=self.set_api_key))
        self.settings_menu.add(rumps.MenuItem(tr("menu.set_base_url"), callback=self.set_base_url))
        
        self.settings_menu.add(None)
        
        last = self.config.get("last_request_tokens", 0)
        total = self.config.get("used_tokens", 0)
        
        self.last_request_item = rumps.MenuItem(tr("menu.tokens_last", value=last), callback=None)
        self.total_tokens_item = rumps.MenuItem(tr("menu.tokens_used", value=total), callback=None)
        
        self.settings_menu.add(self.last_request_item)
        self.settings_menu.add(self.total_tokens_item)
        
        self.settings_menu.add(None)
        self.settings_menu.add(messageAuthor)
        
        if HAS_PYOBJC:
            try:
                self.last_request_item._menuitem.setEnabled_(False)
                self.total_tokens_item._menuitem.setEnabled_(False)
            except:
                pass

    def open_main_window(self, _=None):
        if HAS_PYOBJC and not self.config.get("permissions_onboarding_done", False):
            self.show_permissions_window()
            return
        if self.window_controller:
            self.window_controller.show_window()

    def run_on_main(self, fn, *args):
        if HAS_PYOBJC:
            if NSThread.isMainThread():
                fn(*args)
                return
            try:
                AppHelper.callAfter(fn, *args)
                return
            except Exception as e:
                logger.warning(f"callAfter failed, skipping direct background UI call: {e}")
                return
        fn(*args)

    def _refresh_ui_main(self):
        self.update_ui_state()
        self.refresh_files_menus()
        if self.window_controller:
            self.window_controller.refresh_all()

    def request_ui_refresh(self):
        self.run_on_main(self._refresh_ui_main)

    def request_set_state_icon(self, state):
        self.run_on_main(self.set_state_icon, state)

    def request_flash_error(self):
        self.run_on_main(self.flash_error)

    def update_token_stats(self):
        last = self.config.get("last_request_tokens", 0)
        total = self.config.get("used_tokens", 0)
        if hasattr(self, 'last_request_item'):
            self.last_request_item.title = tr("menu.tokens_last", value=last)
        if hasattr(self, 'total_tokens_item'):
            self.total_tokens_item.title = tr("menu.tokens_used", value=total)
        if self.window_controller:
            self.window_controller.refresh_all()

    def set_video_quality_value(self, quality_name):
        if quality_name not in VIDEO_QUALITY_PRESETS:
            return
        self.config["video_quality"] = quality_name
        for item in self.quality_menu.values():
            item.state = 1 if item.title == quality_name else 0
        ConfigManager.save(self.config)
        if self.window_controller:
            self.window_controller.refresh_all()

    def set_ai_model_value(self, model_name):
        if model_name not in AI_MODELS:
            return
        self.config["model_name"] = model_name
        for item in self.model_menu.values():
            item.state = 1 if item.title == model_name else 0
        ConfigManager.save(self.config)
        if self.window_controller:
            self.window_controller.refresh_all()

    def select_video_quality(self, sender):
        self.set_video_quality_value(sender.title)

    def select_ai_model(self, sender):
        self.set_ai_model_value(sender.title)

    def edit_prompt(self, _):
        w = rumps.Window(
            tr("dialog.edit_prompt.title"),
            tr("dialog.edit_prompt.instructions"),
            self.config["prompt"],
            dimensions=(600, 200)
        )
        r = w.run()
        if r.clicked:
            self.config["prompt"] = r.text.strip()
            ConfigManager.save(self.config)
            if self.window_controller:
                self.window_controller.refresh_all()

    def set_api_key(self, _):
        w = rumps.Window(tr("dialog.api_key.title"), default_text=self.config["api_key"], dimensions=(600, 50))
        r = w.run()
        if r.clicked:
            self.config["api_key"] = r.text.strip()
            ConfigManager.save(self.config)
            if self.window_controller:
                self.window_controller.refresh_all()

    def set_base_url(self, _):
        current = (self.config.get("base_url") or DEFAULT_CONFIG.get("base_url", "")).strip()
        w = rumps.Window(
            tr("dialog.base_url.title"),
            tr("dialog.base_url.instructions"),
            current,
            dimensions=(620, 50)
        )
        r = w.run()
        if not r.clicked:
            return

        value = (r.text or "").strip()
        self.config["base_url"] = value or DEFAULT_CONFIG.get("base_url", "")
        ConfigManager.save(self.config)
        if self.window_controller:
            self.window_controller.refresh_all()

    def reset_permissions(self, _):
        try:
            result = subprocess.run(
                ["tccutil", "reset", "All", APP_BUNDLE_ID],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout or "Unknown error").strip()
                rumps.alert(
                    tr("reset.failed_title"),
                    tr("reset.failed_with_details", details=details)
                )
                return

            # Opens the exact privacy pane so the user can re-enable screen access immediately.
            subprocess.call(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"])
            rumps.alert(
                tr("reset.done_title"),
                tr("reset.done_body")
            )
        except Exception as e:
            rumps.alert(tr("reset.failed_title"), tr("reset.failed_generic", error=e))

    def reset_permissions_and_restart(self, _):
        try:
            result = subprocess.run(
                ["tccutil", "reset", "All", APP_BUNDLE_ID],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout or "Unknown error").strip()
                rumps.alert(
                    tr("reset.failed_title"),
                    tr("reset.failed_with_details", details=details)
                )
                return

            bundle_path = None
            if HAS_PYOBJC:
                try:
                    bundle_path = NSBundle.mainBundle().bundlePath()
                except Exception:
                    bundle_path = None

            if bundle_path and os.path.exists(bundle_path):
                subprocess.Popen(["open", "-n", bundle_path])
                rumps.quit_application()
            else:
                rumps.alert(
                    tr("reset.relaunch_missing_app_title"),
                    tr("reset.relaunch_missing_app_body")
                )
        except Exception as e:
            rumps.alert(tr("reset.failed_title"), tr("reset.failed_generic", error=e))
            
    def open_folder(self, _):
        subprocess.call(["open", self.config["save_dir"]])

    def open_link(self, _):
        subprocess.call(["open", "https://t.me/galay_ss"])

    def record_switch(self, sender):
        if HAS_PYOBJC and not self.config.get("permissions_onboarding_done", False):
            rumps.alert(tr("record.permissions_required_title"), tr("record.permissions_required_body"))
            self.show_permissions_window()
            return

        # Protection against starting recording while processing
        if self.is_processing and not self.is_recording:
            rumps.alert(tr("record.busy_title"), tr("record.busy_body"))
            return
        if self.is_waiting_permissions:
            rumps.alert(tr("record.please_wait_title"), tr("record.please_wait_body"))
            return

        if not self.is_recording:
            if not self.config.get("api_key"):
                rumps.alert(tr("record.api_key_required_title"), tr("record.api_key_required_body"))
                return
            self.start_recording(sender)
        else:
            self.stop_recording(sender)

    def _set_start_stop_title(self, new_title):
        if not hasattr(self, "start_stop_item"):
            return
        is_stop = (new_title == "Stop")
        self.start_stop_item.title = tr("menu.stop_recording") if is_stop else tr("menu.start_recording")

    # --- START RECORDING (ОБНОВЛЕННЫЙ) ---
    def start_recording(self, sender):
        if self.is_waiting_permissions:
            return

        # Do not request permissions here.
        # Permissions are handled explicitly in onboarding window.
        if HAS_PYOBJC:
            if not PermissionManager.is_mic_authorized() or not PermissionManager.is_screen_authorized():
                rumps.alert(
                    tr("record.permissions_required_title"),
                    tr("record.permissions_missing_body")
                )
                self.config["permissions_onboarding_done"] = False
                ConfigManager.save(self.config)
                self.show_permissions_window()
                return

        timestamp = datetime.now().strftime("%d.%m.%Y_%H:%M:%S")
        
        # 1. Основной файл (Видео + Системный звук)
        self.current_filename = os.path.join(self.config["save_dir"], f"Meet_{timestamp}.mp4")
        # 2. Микрофон (только аудио, формат M4A)
        self.mic_audio_filename = os.path.join(self.config["save_dir"], f"Meet_{timestamp}_mic.m4a")
        
        logger.info(f"Starting Recording. Main: {self.current_filename}, Mic: {self.mic_audio_filename}")
        
        try:
            self.start_attempt_id += 1
            attempt_id = self.start_attempt_id
            self.is_waiting_permissions = True
            self.set_state_icon("awaiting_permission")
            self.request_ui_refresh()

            url_main = NSURL.fileURLWithPath_(self.current_filename)
            url_mic = NSURL.fileURLWithPath_(self.mic_audio_filename)
            
            # Получаем настройки качества
            quality_key = self.config.get("video_quality", "Medium")
            preset = VIDEO_QUALITY_PRESETS.get(quality_key, VIDEO_QUALITY_PRESETS["Medium"])

            # ВАЖНО: Инициализация рекордера с двумя URL и конфигом
            self.recorder = ScreenRecorder.alloc().initWithOutputURLs_auxURL_videoConfig_(
                url_main, url_mic, preset
            )
            
            if not self.recorder:
                raise Exception("Failed to initialize ScreenRecorder")

            # Callback для обработки результата запуска записи
            def start_callback(success, error_msg):
                if attempt_id != self.start_attempt_id:
                    return
                if not success:
                    logger.error(f"Failed to start recording: {error_msg}")
                    def handle_failure():
                        rumps.alert(
                            tr("record.recording_error_title"),
                            tr("record.recording_error_body", error=error_msg)
                        )
                        # Сбрасываем UI в исходное состояние
                        self.is_waiting_permissions = False
                        self.is_recording = False
                        if sender:
                            sender.title = tr("main.start_recording")
                        self._set_start_stop_title("Start Recording")
                        self.set_state_icon("idle")
                        self.recorder = None
                        self.request_ui_refresh()
                    self.run_on_main(handle_failure)
                else:
                    def handle_success():
                        if attempt_id != self.start_attempt_id:
                            return
                        self.is_waiting_permissions = False
                        self.is_recording = True
                        if sender:
                            sender.title = tr("main.stop_recording")
                        self._set_start_stop_title("Stop")
                        self.set_state_icon("recording")
                        self.request_ui_refresh()
                    self.run_on_main(handle_success)

            self.recorder.startWithCallback_(start_callback)

            def start_timeout_watchdog():
                time.sleep(15)
                if attempt_id != self.start_attempt_id:
                    return
                if not self.is_waiting_permissions:
                    return

                def handle_timeout():
                    if attempt_id != self.start_attempt_id or not self.is_waiting_permissions:
                        return
                    self.is_waiting_permissions = False
                    self.is_recording = False
                    self._set_start_stop_title("Start Recording")
                    self.set_state_icon("error")
                    self.request_ui_refresh()
                    rumps.alert(
                        tr("record.start_timeout_title"),
                        tr("record.start_timeout_body")
                    )
                self.run_on_main(handle_timeout)

            threading.Thread(target=start_timeout_watchdog, daemon=True).start()
            
        except Exception as e:
            logger.exception("Recording failed to start")
            self.is_waiting_permissions = False
            rumps.alert(tr("common.error"), str(e))
            self.set_state_icon("error")
            self.request_ui_refresh()

    def stop_recording(self, sender):
        logger.info("Stopping native recording...")
        self.is_waiting_permissions = False
        if self.recorder:
            self.recorder.stop()
        
        self.is_recording = False
        if sender:
            sender.title = tr("main.start_recording")
        self._set_start_stop_title("Start Recording")
        self.set_state_icon("idle")
        
        rumps.notification(
            tr("record.saved_title"),
            tr("record.saved_body"),
            os.path.basename(self.current_filename)
        )
        # Даем время на закрытие файлов
        time.sleep(1.0)
        self.refresh_files_menus()

    def list_recent_recordings(self, limit=10):
        save_dir = self.config["save_dir"]
        if not os.path.exists(save_dir):
            return []
        all_files = [f for f in os.listdir(save_dir) if f.lower().endswith(".mp4")]
        all_files.sort(key=lambda x: os.path.getmtime(os.path.join(save_dir, x)), reverse=True)

        hidden = self._get_hidden_recordings()
        if not hidden:
            return all_files[:limit]

        # Auto-clean stale hidden entries when files no longer exist on disk.
        existing = set(all_files)
        stale_hidden = hidden - existing
        if stale_hidden:
            self._set_hidden_recordings(hidden - stale_hidden)
            hidden = self._get_hidden_recordings()

        files = [f for f in all_files if f not in hidden]
        return files[:limit]

    def list_recent_protocols(self, limit=10):
        save_dir = self.config["save_dir"]
        if not os.path.exists(save_dir):
            return []
        files = [f for f in os.listdir(save_dir) if f.endswith("_protocol.txt")]
        files.sort(key=lambda x: os.path.getmtime(os.path.join(save_dir, x)), reverse=True)
        return files[:limit]

    # --- REFRESH MENU (С ФИЛЬТРАЦИЕЙ СИСТЕМНЫХ ФАЙЛОВ) ---
    def refresh_files_menus(self, _=None):
        try:
            # Очистка меню видео
            for item_title in list(self.recent_recordings_menu.keys()):
                del self.recent_recordings_menu[item_title]
            
            recordings = self.list_recent_recordings(limit=10)
            if recordings:
                for f in recordings:
                    self.recent_recordings_menu.add(rumps.MenuItem(f, callback=self.process_selected_file))
            else:
                self.recent_recordings_menu.add(rumps.MenuItem(tr("menu.empty"), callback=None))

            # Очистка меню протоколов
            for item_title in list(self.recent_protocols_menu.keys()):
                del self.recent_protocols_menu[item_title]

            protocols = self.list_recent_protocols(limit=10)
            if protocols:
                for f in protocols:
                    self.recent_protocols_menu.add(rumps.MenuItem(f, callback=self.open_protocol_file))
            else:
                self.recent_protocols_menu.add(rumps.MenuItem(tr("menu.empty"), callback=None))

            if self.window_controller:
                self.window_controller.refresh_file_lists()
        except Exception as e:
            logger.warning(f"Menu refresh warning: {e}")

    def open_protocol_by_name(self, filename):
        subprocess.call(["open", os.path.join(self.config["save_dir"], filename)])

    def open_protocol_file(self, sender):
        self.open_protocol_by_name(sender.title)

    def _paths_for_recording(self, filename):
        base = os.path.splitext(filename)[0]
        save_dir = self.config["save_dir"]
        return {
            "video": os.path.join(save_dir, filename),
            "mic": os.path.join(save_dir, base + "_mic.m4a"),
            "protocol": os.path.join(save_dir, base + "_protocol.txt")
        }

    def _get_hidden_recordings(self):
        raw = self.config.get("hidden_recordings", [])
        if isinstance(raw, list):
            return set(str(x) for x in raw if isinstance(x, str) and x)
        return set()

    def _set_hidden_recordings(self, hidden_set):
        self.config["hidden_recordings"] = sorted(hidden_set)
        ConfigManager.save(self.config)

    def _hide_recording_entry(self, filename):
        if not filename:
            return
        hidden = self._get_hidden_recordings()
        if filename in hidden:
            return
        hidden.add(filename)
        self._set_hidden_recordings(hidden)

    def _unhide_recording_entry(self, filename):
        if not filename:
            return
        hidden = self._get_hidden_recordings()
        if filename not in hidden:
            return
        hidden.remove(filename)
        self._set_hidden_recordings(hidden)

    def _is_recording_locked_for_edit(self, filename):
        active_recording_name = os.path.basename(self.current_filename) if self.current_filename else None
        if self.is_recording and active_recording_name == filename:
            rumps.alert(tr("blocked.title"), tr("blocked.recording"))
            return True
        if self.current_processing_file == filename:
            rumps.alert(tr("blocked.title"), tr("blocked.processing"))
            return True
        return False

    def _sanitize_recording_base_name(self, raw_name):
        name = (raw_name or "").strip()
        if name.lower().endswith(".mp4"):
            name = name[:-4].strip()
        name = name.replace("/", " ").replace(":", "-")
        name = re.sub(r"\s+", " ", name).strip().strip(".")
        return name

    def rename_recording_interactive(self, filename):
        if not filename:
            return None
        if self._is_recording_locked_for_edit(filename):
            return None

        current_base = os.path.splitext(filename)[0]
        w = rumps.Window(tr("rename.title"), tr("rename.prompt"), current_base, dimensions=(520, 50))
        result = w.run()
        if not result.clicked:
            return None

        new_base = self._sanitize_recording_base_name(result.text)
        if not new_base:
            rumps.alert(tr("rename.error_title"), tr("rename.error_empty"))
            return None
        if new_base == current_base:
            return filename

        new_filename = f"{new_base}.mp4"
        old_paths = self._paths_for_recording(filename)
        new_paths = self._paths_for_recording(new_filename)

        rename_ops = []
        if not os.path.exists(old_paths["video"]):
            rumps.alert(tr("rename.error_title"), tr("rename.error_source_missing"))
            return None
        rename_ops.append((old_paths["video"], new_paths["video"]))
        if os.path.exists(old_paths["mic"]):
            rename_ops.append((old_paths["mic"], new_paths["mic"]))
        if os.path.exists(old_paths["protocol"]):
            rename_ops.append((old_paths["protocol"], new_paths["protocol"]))

        for src, dst in rename_ops:
            if os.path.abspath(src) == os.path.abspath(dst):
                continue
            if os.path.exists(dst):
                rumps.alert(tr("rename.error_title"), tr("rename.error_exists", filename=os.path.basename(dst)))
                return None

        renamed = []
        try:
            for src, dst in rename_ops:
                if os.path.abspath(src) == os.path.abspath(dst):
                    continue
                os.rename(src, dst)
                renamed.append((src, dst))
        except Exception as e:
            for src, dst in reversed(renamed):
                try:
                    if os.path.exists(dst) and not os.path.exists(src):
                        os.rename(dst, src)
                except Exception:
                    pass
            rumps.alert(tr("rename.error_title"), str(e))
            return None

        hidden = self._get_hidden_recordings()
        if filename in hidden:
            hidden.remove(filename)
            hidden.add(new_filename)
            self._set_hidden_recordings(hidden)

        rumps.notification(tr("rename.done_title"), tr("rename.done_body"), new_filename)
        self.request_ui_refresh()
        return new_filename

    def archive_recording_interactive(self, filename):
        if not filename:
            return False
        if self._is_recording_locked_for_edit(filename):
            return False

        confirmed = False
        if HAS_PYOBJC:
            alert = NSAlert.alloc().init()
            alert.setMessageText_(tr("archive.confirm_title"))
            alert.setInformativeText_(tr("archive.confirm_body", filename=filename))
            try:
                alert.setAlertStyle_(NSAlertStyleWarning)
            except Exception:
                pass
            alert.addButtonWithTitle_(tr("archive.confirm_button"))
            alert.addButtonWithTitle_(tr("common.cancel"))
            confirmed = (alert.runModal() == 1000)
        else:
            confirmed = bool(rumps.alert(tr("archive.confirm_title"), tr("archive.confirm_fallback_body")))
        if not confirmed:
            return False

        self._hide_recording_entry(filename)
        rumps.notification(tr("archive.done_title"), tr("archive.done_body"), filename)
        self.request_ui_refresh()
        return True

    def delete_recording_with_files_interactive(self, filename):
        if not filename:
            return False
        if self._is_recording_locked_for_edit(filename):
            return False

        confirmed = False
        if HAS_PYOBJC:
            alert = NSAlert.alloc().init()
            alert.setMessageText_(tr("delete.confirm_title"))
            alert.setInformativeText_(tr("delete.confirm_body", filename=filename))
            try:
                alert.setAlertStyle_(NSAlertStyleWarning)
            except Exception:
                pass
            alert.addButtonWithTitle_(tr("delete.confirm_button"))
            alert.addButtonWithTitle_(tr("common.cancel"))
            confirmed = (alert.runModal() == 1000)
        else:
            confirmed = bool(rumps.alert(tr("delete.confirm_title"), tr("delete.confirm_fallback_body")))
        if not confirmed:
            return False

        paths = self._paths_for_recording(filename)
        to_delete = [paths["video"], paths["mic"], paths["protocol"]]

        removed = []
        failed = []
        for path in to_delete:
            if not os.path.exists(path):
                continue
            try:
                os.remove(path)
                removed.append(os.path.basename(path))
            except Exception as e:
                failed.append(f"{os.path.basename(path)}: {e}")

        if removed:
            rumps.notification(tr("delete.done_title"), tr("delete.done_body"), ", ".join(removed)[:80])
        if failed:
            rumps.alert(tr("delete.error_title"), "\n".join(failed))

        self._unhide_recording_entry(filename)
        self.request_ui_refresh()
        return not failed

    # Compatibility alias for older call sites.
    def delete_recording_interactive(self, filename):
        return self.delete_recording_with_files_interactive(filename)

    def process_video_file(self, filename, prompt_override=None):
        if self.is_processing:
            return
        video_path = os.path.join(self.config["save_dir"], filename)
        if os.path.exists(video_path):
            self.current_processing_file = filename
            threading.Thread(
                target=process_video_with_ai,
                args=(video_path, self.config, self, prompt_override),
                daemon=True
            ).start()

    def process_selected_file(self, sender):
        self.process_video_file(sender.title)

if HAS_PYOBJC:
    class MenuDelegate(NSObject):
        def initWithApp_(self, app):
            self = objc.super(MenuDelegate, self).init()
            if self: self.app = app
            return self
        
        def menuWillOpen_(self, menu):
            if not self.app.is_recording:
                self.app.refresh_files_menus()

if __name__ == "__main__":
    app = RecorderApp()
    app.run()
