import logging
import os
import threading
import time
from datetime import datetime

import rumps
from Foundation import NSURL

from steno_app.recorder import ScreenRecorder
from steno_app.config import ConfigManager, VIDEO_QUALITY_PRESETS
from steno_app.i18n import tr


logger = logging.getLogger("Steno")


class RecordingService:
    def __init__(self, app, has_pyobjc):
        self.app = app
        self.has_pyobjc = bool(has_pyobjc)

    def record_switch(self, sender):
        if self.has_pyobjc and not self.app.config.get("permissions_onboarding_done", False):
            rumps.alert(tr("record.permissions_required_title"), tr("record.permissions_required_body"))
            self.app.show_permissions_window()
            return

        # Protection against starting recording while processing
        if self.app.is_processing and not self.app.is_recording:
            rumps.alert(tr("record.busy_title"), tr("record.busy_body"))
            return
        if self.app.is_waiting_permissions:
            rumps.alert(tr("record.please_wait_title"), tr("record.please_wait_body"))
            return

        if not self.app.is_recording:
            self.start_recording(sender)
        else:
            self.stop_recording(sender)

    def start_recording(self, sender):
        if self.app.is_waiting_permissions:
            return

        # Do not request permissions here.
        # Permissions are handled explicitly in onboarding window.
        if self.has_pyobjc:
            if not self.app.permission_manager.is_mic_authorized() or not self.app.permission_manager.is_screen_authorized():
                rumps.alert(
                    tr("record.permissions_required_title"),
                    tr("record.permissions_missing_body"),
                )
                self.app.config["permissions_onboarding_done"] = False
                ConfigManager.save(self.app.config)
                self.app.show_permissions_window()
                return

        timestamp = datetime.now().strftime("%d.%m.%Y_%H:%M:%S")

        # 1. Основной файл (Видео + Системный звук)
        self.app.current_filename = os.path.join(self.app.config["save_dir"], f"Meet_{timestamp}.mp4")
        # 2. Микрофон (только аудио, формат M4A)
        self.app.mic_audio_filename = os.path.join(self.app.config["save_dir"], f"Meet_{timestamp}_mic.m4a")

        logger.info(f"Starting Recording. Main: {self.app.current_filename}, Mic: {self.app.mic_audio_filename}")

        try:
            self.app.start_attempt_id += 1
            attempt_id = self.app.start_attempt_id
            self.app.is_waiting_permissions = True
            self.app.set_state_icon("awaiting_permission")
            self.app.request_ui_refresh()

            url_main = NSURL.fileURLWithPath_(self.app.current_filename)
            url_mic = NSURL.fileURLWithPath_(self.app.mic_audio_filename)

            # Получаем настройки качества
            quality_key = self.app.config.get("video_quality", "Medium")
            preset = VIDEO_QUALITY_PRESETS.get(quality_key, VIDEO_QUALITY_PRESETS["Medium"])

            # ВАЖНО: Инициализация рекордера с двумя URL и конфигом
            self.app.recorder = ScreenRecorder.alloc().initWithOutputURLs_auxURL_videoConfig_(
                url_main, url_mic, preset
            )

            if not self.app.recorder:
                raise Exception("Failed to initialize ScreenRecorder")

            # Callback для обработки результата запуска записи
            def start_callback(success, error_msg):
                if attempt_id != self.app.start_attempt_id:
                    return
                if not success:
                    logger.error(f"Failed to start recording: {error_msg}")

                    def handle_failure():
                        rumps.alert(
                            tr("record.recording_error_title"),
                            tr("record.recording_error_body", error=error_msg),
                        )
                        # Сбрасываем UI в исходное состояние
                        self.app.is_waiting_permissions = False
                        self.app.is_recording = False
                        self.app.recording_started_at = None
                        if sender:
                            sender.title = tr("main.start_recording")
                        self.app._set_start_stop_title("Start Recording")
                        self.app.set_state_icon("idle")
                        self.app.recorder = None
                        self.app.request_ui_refresh()

                    self.app.run_on_main(handle_failure)
                else:

                    def handle_success():
                        if attempt_id != self.app.start_attempt_id:
                            return
                        self.app.is_waiting_permissions = False
                        self.app.is_recording = True
                        self.app.recording_started_at = time.time()
                        if sender:
                            sender.title = tr("main.stop_recording")
                        self.app._set_start_stop_title("Stop")
                        self.app.set_state_icon("recording")
                        self.app.request_ui_refresh()
                        if self.app.window_controller and self.app.current_filename:
                            active_name = os.path.basename(self.app.current_filename)
                            self.app.window_controller.focus_recording(active_name)

                    self.app.run_on_main(handle_success)

            self.app.recorder.startWithCallback_(start_callback)

            def start_timeout_watchdog():
                time.sleep(15)
                if attempt_id != self.app.start_attempt_id:
                    return
                if not self.app.is_waiting_permissions:
                    return

                def handle_timeout():
                    if attempt_id != self.app.start_attempt_id or not self.app.is_waiting_permissions:
                        return
                    self.app.is_waiting_permissions = False
                    self.app.is_recording = False
                    self.app.recording_started_at = None
                    self.app._set_start_stop_title("Start Recording")
                    self.app.set_state_icon("error")
                    self.app.request_ui_refresh()
                    rumps.alert(
                        tr("record.start_timeout_title"),
                        tr("record.start_timeout_body"),
                    )

                self.app.run_on_main(handle_timeout)

            threading.Thread(target=start_timeout_watchdog, daemon=True).start()

        except Exception as e:
            logger.exception("Recording failed to start")
            self.app.is_waiting_permissions = False
            self.app.recording_started_at = None
            rumps.alert(tr("common.error"), str(e))
            self.app.set_state_icon("error")
            self.app.request_ui_refresh()

    def stop_recording(self, sender):
        logger.info("Stopping native recording...")
        self.app.is_waiting_permissions = False
        if self.app.recorder:
            self.app.recorder.stop()

        self.app.is_recording = False
        self.app.recording_started_at = None
        if sender:
            sender.title = tr("main.start_recording")
        self.app._set_start_stop_title("Start Recording")
        self.app.set_state_icon("idle")

        rumps.notification(
            tr("record.saved_title"),
            tr("record.saved_body"),
            os.path.basename(self.app.current_filename),
        )
        # Даем время на закрытие файлов
        time.sleep(1.0)
        self.app.refresh_files_menus()
