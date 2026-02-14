import logging
import threading

import objc
import rumps
from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSFont,
    NSTextField,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject

from steno.i18n import tr


logger = logging.getLogger("Steno")


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
            False,
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
            secondary=True,
        )
        root.addSubview_(desc)

        self.screen_status = self._label(
            ((24.0, 248.0), (500.0, 28.0)),
            tr("permissions.screen_status", status=tr("permissions.status.unknown")),
            bold=True,
        )
        root.addSubview_(self.screen_status)
        self.screen_button = self._button(
            ((540.0, 244.0), (190.0, 34.0)),
            tr("permissions.request_screen"),
            "onRequestScreen:",
        )
        root.addSubview_(self.screen_button)

        self.mic_status = self._label(
            ((24.0, 180.0), (500.0, 28.0)),
            tr("permissions.mic_status", status=tr("permissions.status.unknown")),
            bold=True,
        )
        root.addSubview_(self.mic_status)
        self.mic_button = self._button(
            ((540.0, 176.0), (190.0, 34.0)),
            tr("permissions.request_mic"),
            "onRequestMic:",
        )
        root.addSubview_(self.mic_button)

        self.hint_label = self._label(
            ((24.0, 70.0), (710.0, 70.0)),
            tr("permissions.hint"),
            secondary=True,
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
            screen_granted = self.app.permission_manager.is_screen_authorized()
            mic_granted = self.app.permission_manager.is_mic_authorized()
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
            self.app.permission_manager._request_screen_access_blocking()
            self.app.run_on_main(self.refresh_statuses)

        threading.Thread(target=request_and_refresh, daemon=True).start()

    def onRequestMic_(self, _):
        self.mic_requested = True

        def completion(granted):
            logger.info(f"Mic permission granted from onboarding: {granted}")
            self.app.run_on_main(self.refresh_statuses)

        AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, completion)
        self.refresh_statuses()

