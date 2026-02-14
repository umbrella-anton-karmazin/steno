"""Backward-compatible import shim.

Use `MeetingsService` from `steno.services.meetings_service`.
"""

from steno.services.meetings_service import MeetingsService


# Backward compatibility for older imports.
LibraryService = MeetingsService
