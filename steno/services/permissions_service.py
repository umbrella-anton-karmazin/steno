import logging
import threading


logger = logging.getLogger("Steno")


try:
    from AVFoundation import AVCaptureDevice, AVMediaTypeAudio, AVAuthorizationStatusAuthorized
    from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess
    from UserNotifications import (
        UNUserNotificationCenter,
        UNAuthorizationOptionAlert,
        UNAuthorizationOptionSound,
        UNAuthorizationOptionBadge,
    )

    HAS_PERMISSION_APIS = True
except Exception:
    HAS_PERMISSION_APIS = False


class PermissionManager:
    @staticmethod
    def is_mic_authorized():
        if not HAS_PERMISSION_APIS:
            return False
        return AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio) == AVAuthorizationStatusAuthorized

    @staticmethod
    def is_screen_authorized():
        if not HAS_PERMISSION_APIS:
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
        if not HAS_PERMISSION_APIS:
            return
        logger.info("Checking system permissions...")

        mic_status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        if mic_status != AVAuthorizationStatusAuthorized:
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVMediaTypeAudio,
                lambda granted: logger.info(f"Mic permission granted: {granted}"),
            )

        if not CGPreflightScreenCaptureAccess():
            # CGRequestScreenCaptureAccess can block until the user responds.
            # Run it outside UI/main thread to avoid app freeze.
            threading.Thread(
                target=PermissionManager._request_screen_access_blocking,
                daemon=True,
            ).start()

        center = UNUserNotificationCenter.currentNotificationCenter()
        options = UNAuthorizationOptionAlert | UNAuthorizationOptionSound | UNAuthorizationOptionBadge
        center.requestAuthorizationWithOptions_completionHandler_(
            options,
            lambda granted, error: logger.info(f"Notifications permission granted: {granted}"),
        )

