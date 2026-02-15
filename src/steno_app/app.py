# app.py
import rumps
import subprocess
import os
import signal
import threading
import time
import sys
import certifi
import shutil
import logging

from steno_app.config import (
    AI_MODELS,
    DEFAULT_CONFIG,
    ICON_ERROR,
    ICON_IDLE,
    ICON_PROCESSING,
    ICON_RECORDING,
    VIDEO_QUALITY_PRESETS,
    ConfigManager,
)
from steno_app.i18n import tr
from steno_app.services.permissions_service import PermissionManager
from steno_app.services.processing_service import process_video_with_ai
from steno_app.services.recording_service import RecordingService
from steno_app.services.meetings_service import MeetingsService

messageAuthor = 'v1.4'

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
    from Foundation import NSObject, NSRunLoop, NSDate, NSIndexSet, NSThread, NSLocale
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

if HAS_PYOBJC:
    from steno_app.ui.main_window import MainWindowController
    from steno_app.ui.menu_delegate import MenuDelegate
    from steno_app.ui.permissions_window import PermissionWindowController
else:
    MainWindowController = None
    MenuDelegate = None
    PermissionWindowController = None

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
        self.recording_started_at = None
        self.status_item_hidden = False
        self.permissions_transition_started = False
        self.permission_manager = PermissionManager
        self.recording_service = RecordingService(self, HAS_PYOBJC)
        self.meetings_service = MeetingsService(self, HAS_PYOBJC)
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
            # Startup watchdog: if first dispatch is missed, retry once.
            watchdog = threading.Timer(1.5, self._startup_ui_watchdog)
            watchdog.daemon = True
            watchdog.start()

        logger.info("Steno initialized (Dual-Stream Mode)")

    def _startup_ui_watchdog(self):
        if not HAS_PYOBJC:
            return
        if self.window_controller or self.permission_controller:
            return
        logger.warning("Startup watchdog: no window controller yet, retrying initial UI flow")
        try:
            self._start_initial_ui_flow()
        except Exception:
            logger.exception("Startup watchdog failed")

    def _start_initial_ui_flow(self):
        def worker():
            logger.info("Initial UI flow: starting permission preflight")
            try:
                screen_ok = self.permission_manager.safe_is_screen_authorized(timeout_sec=1.5, default=False)
                mic_ok = self.permission_manager.safe_is_mic_authorized(timeout_sec=1.5, default=False)
            except Exception:
                logger.exception("Failed to preflight permissions")
                screen_ok = False
                mic_ok = False
            logger.info("Initial UI flow: preflight result screen=%s mic=%s", screen_ok, mic_ok)

            def apply_state():
                if screen_ok and mic_ok:
                    if not self.config.get("permissions_onboarding_done", False):
                        self.config["permissions_onboarding_done"] = True
                        ConfigManager.save(self.config)
                    self.ensure_main_window()
                    return

                logger.info("Required permissions are missing. Opening permissions window.")
                if self.config.get("permissions_onboarding_done", False):
                    self.config["permissions_onboarding_done"] = False
                    ConfigManager.save(self.config)
                self.show_permissions_window()

            self.run_on_main(apply_state)

        threading.Thread(target=worker, daemon=True).start()

    def ensure_main_window(self):
        try:
            if not self.window_controller:
                self.window_controller = MainWindowController.alloc().initWithApp_(self)
            self.window_controller.show_window()
        except Exception:
            logger.exception("Failed to open main window")

    def show_permissions_window(self):
        try:
            if not self.permission_controller:
                self.permission_controller = PermissionWindowController.alloc().initWithApp_(self)
            self.permission_controller.show_window()
        except Exception:
            logger.exception("Failed to open permissions window")

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
            # Defer main window construction to the next runloop tick.
            # This avoids doing a heavy window transition directly from
            # permission/TCC callback context in bundled app.
            def open_main_later():
                self.ensure_main_window()
                self.permissions_transition_started = False

            try:
                AppHelper.callAfter(open_main_later)
            except Exception:
                self.run_on_main(open_main_later)
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
        # Keep status item visible until at least one app window is created.
        # This gives user a recovery path ("Open UI") if initial window flow stalls.
        if not self.window_controller and not self.permission_controller:
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

    @rumps.timer(1.0)
    def update_ui_state(self, _=None):
        """
        Updates the enabled/disabled state of menu items based on current app state.
        Runs periodically on the main thread to ensure UI safety.
        
        Rules:
        1. If Processing (is_processing=True):
           - Disable "Recent Recordings" (prevent parallel AI)
           - Disable "Start Recording" (prevent recording during AI) -> BUT allow "Stop" if recording.
           
        2. If Recording (is_recording=True):
           - Keep "Recent Recordings" enabled (allow processing other meetings during recording).
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
        
        # Can use Recent Recordings unless processing is already running.
        can_use_recent = not (self.is_processing or self.is_waiting_permissions)

        idle_mode = not self.is_recording and not self.is_processing and not self.is_waiting_permissions

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

        if self.window_controller and not idle_mode:
            self.window_controller.refresh_from_state()
            if self.is_recording or self.current_processing_file:
                self.window_controller.refresh_file_lists()
            if self.is_recording:
                self.window_controller.refresh_detail_view()

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

    def run_on_main(self, fn, *args, _retries=3):
        if HAS_PYOBJC:
            if NSThread.isMainThread():
                fn(*args)
                return
            try:
                AppHelper.callAfter(fn, *args)
                return
            except Exception as e:
                if _retries > 0:
                    logger.warning(
                        "callAfter failed, retrying main-thread dispatch (%s retries left): %s",
                        _retries,
                        e,
                    )
                    timer = threading.Timer(
                        0.15,
                        lambda: self.run_on_main(fn, *args, _retries=_retries - 1),
                    )
                    timer.daemon = True
                    timer.start()
                    return
                logger.error("callAfter failed after retries; UI action dropped: %s", e)
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

    def get_live_recording_elapsed_seconds(self):
        if not self.is_recording or self.recording_started_at is None:
            return None
        try:
            return max(0, int(time.time() - float(self.recording_started_at)))
        except Exception:
            return None

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

    def open_folder(self, _):
        subprocess.call(["open", self.config["save_dir"]])

    def open_link(self, _):
        subprocess.call(["open", "https://t.me/galay_ss"])

    def record_switch(self, sender):
        self.recording_service.record_switch(sender)

    def _set_start_stop_title(self, new_title):
        if not hasattr(self, "start_stop_item"):
            return
        is_stop = (new_title == "Stop")
        self.start_stop_item.title = tr("menu.stop_recording") if is_stop else tr("menu.start_recording")

    # --- START RECORDING (ОБНОВЛЕННЫЙ) ---
    def start_recording(self, sender):
        self.recording_service.start_recording(sender)

    def stop_recording(self, sender):
        self.recording_service.stop_recording(sender)

    # --- REFRESH MENU (С ФИЛЬТРАЦИЕЙ СИСТЕМНЫХ ФАЙЛОВ) ---
    def refresh_files_menus(self, _=None):
        try:
            # Очистка меню видео
            for item_title in list(self.recent_recordings_menu.keys()):
                del self.recent_recordings_menu[item_title]
            
            recordings = self.meetings_service.list_recent_recordings(limit=10)
            if recordings:
                for f in recordings:
                    self.recent_recordings_menu.add(rumps.MenuItem(f, callback=self.process_selected_file))
            else:
                self.recent_recordings_menu.add(rumps.MenuItem(tr("menu.empty"), callback=None))

            # Очистка меню протоколов
            for item_title in list(self.recent_protocols_menu.keys()):
                del self.recent_protocols_menu[item_title]

            protocols = self.meetings_service.list_recent_protocols(limit=10)
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

    def process_video_file(
        self,
        filename,
        system_prompt_override=None,
        user_prompt_override=None,
        template_id_override=None,
        prompt_override=None,
    ):
        if self.is_processing:
            return
        api_key = (self.config.get("api_key") or "").strip()
        if not api_key:
            rumps.alert(
                tr("record.api_key_required_title"),
                tr("record.api_key_required_body"),
            )
            self.set_api_key(None)
            return
        video_path = os.path.join(self.config["save_dir"], filename)
        if os.path.exists(video_path):
            # Backward compatibility for older call-sites.
            if system_prompt_override is None and prompt_override is not None:
                system_prompt_override = prompt_override
            self.current_processing_file = filename
            threading.Thread(
                target=process_video_with_ai,
                args=(
                    video_path,
                    self.config,
                    self,
                    system_prompt_override,
                    user_prompt_override,
                    template_id_override,
                ),
                daemon=True
            ).start()

    def process_selected_file(self, sender):
        self.process_video_file(sender.title)

if __name__ == "__main__":
    app = RecorderApp()
    app.run()
