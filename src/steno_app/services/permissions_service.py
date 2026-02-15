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
    def _call_with_timeout(callable_fn, timeout_sec, default_value, label):
        result = {"done": False, "value": default_value}

        def target():
            try:
                result["value"] = callable_fn()
            except Exception as exc:
                logger.warning("%s failed: %s", label, exc)
                result["value"] = default_value
            finally:
                result["done"] = True

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(timeout=max(0.1, float(timeout_sec)))
        if not result["done"]:
            logger.warning("%s timed out after %.2fs; fallback=%s", label, timeout_sec, default_value)
            return default_value
        return result["value"]

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
    def safe_is_mic_authorized(timeout_sec=1.5, default=False):
        return bool(
            PermissionManager._call_with_timeout(
                PermissionManager.is_mic_authorized,
                timeout_sec,
                bool(default),
                "Mic permission preflight",
            )
        )

    @staticmethod
    def safe_is_screen_authorized(timeout_sec=1.5, default=False):
        return bool(
            PermissionManager._call_with_timeout(
                PermissionManager.is_screen_authorized,
                timeout_sec,
                bool(default),
                "Screen permission preflight",
            )
        )

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
