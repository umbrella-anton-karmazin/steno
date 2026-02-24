import os
import re
import shutil
import threading
import time

import rumps

from steno_app.config import ConfigManager
from steno_app.i18n import tr


try:
    from AppKit import NSAlert, NSAlertStyleWarning
except Exception:
    NSAlert = None
    NSAlertStyleWarning = None


class MeetingsService:
    SUPPORTED_MEETING_EXTENSIONS = {
        ".mp4",
        ".mov",
        ".m4v",
        ".mkv",
        ".webm",
        ".avi",
        ".m4a",
        ".mp3",
        ".wav",
        ".aac",
        ".flac",
        ".ogg",
    }

    def __init__(self, app, has_pyobjc):
        self.app = app
        self.has_pyobjc = bool(has_pyobjc)

    def _is_primary_meeting_media(self, filename):
        if not filename or filename.startswith("."):
            return False
        name = str(filename)
        lower = name.lower()
        if lower.endswith("_protocol.txt") or lower.endswith("_protocol.meta.json"):
            return False
        if lower.endswith("_mic.m4a"):
            return False
        ext = os.path.splitext(lower)[1]
        return ext in self.SUPPORTED_MEETING_EXTENSIONS

    def list_recent_recordings(self, limit=10):
        save_dir = self.app.config["save_dir"]
        if not os.path.exists(save_dir):
            return []
        all_files = [f for f in os.listdir(save_dir) if self._is_primary_meeting_media(f)]
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
        save_dir = self.app.config["save_dir"]
        if not os.path.exists(save_dir):
            return []
        files = [f for f in os.listdir(save_dir) if f.endswith("_protocol.txt")]
        files.sort(key=lambda x: os.path.getmtime(os.path.join(save_dir, x)), reverse=True)
        return files[:limit]

    def _paths_for_recording(self, filename):
        base = os.path.splitext(filename)[0]
        save_dir = self.app.config["save_dir"]
        return {
            "video": os.path.join(save_dir, filename),
            "mic": os.path.join(save_dir, base + "_mic.m4a"),
            "protocol": os.path.join(save_dir, base + "_protocol.txt"),
            "protocol_meta": os.path.join(save_dir, base + "_protocol.meta.json"),
        }

    def _recording_total_size_bytes(self, filename):
        total = 0
        for path in self._paths_for_recording(filename).values():
            if not os.path.exists(path):
                continue
            try:
                total += int(os.path.getsize(path))
            except Exception:
                pass
        return total

    def _format_bytes(self, value):
        size = max(0.0, float(value or 0))
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        while size >= 1024.0 and idx < len(units) - 1:
            size /= 1024.0
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.1f} {units[idx]}"

    def get_library_storage_usage_bytes(self):
        save_dir = self.app.config["save_dir"]
        if not os.path.isdir(save_dir):
            return 0
        total = 0
        try:
            for entry in os.listdir(save_dir):
                path = os.path.join(save_dir, entry)
                if not os.path.isfile(path):
                    continue
                try:
                    total += int(os.path.getsize(path))
                except Exception:
                    pass
        except Exception:
            return 0
        return total

    def get_library_storage_usage_human(self):
        return self._format_bytes(self.get_library_storage_usage_bytes())

    def _collect_cleanup_candidates_older_than(self, older_than_days):
        save_dir = self.app.config["save_dir"]
        if not os.path.isdir(save_dir):
            return []
        try:
            days = int(older_than_days)
        except Exception:
            days = 0
        if days <= 0:
            return []

        cutoff_ts = (time.time() - (days * 24 * 3600))
        active_recording_name = os.path.basename(self.app.current_filename) if self.app.current_filename else ""
        processing_name = str(self.app.current_processing_file or "")

        candidates = []
        for filename in os.listdir(save_dir):
            if not self._is_primary_meeting_media(filename):
                continue
            if filename == active_recording_name or filename == processing_name:
                continue
            path = os.path.join(save_dir, filename)
            try:
                mtime = float(os.path.getmtime(path))
            except Exception:
                continue
            if mtime > cutoff_ts:
                continue
            candidates.append(filename)
        return candidates

    def estimate_cleanup_older_than(self, older_than_days):
        candidates = self._collect_cleanup_candidates_older_than(older_than_days)
        total_bytes = 0
        for filename in candidates:
            total_bytes += self._recording_total_size_bytes(filename)
        return {
            "count": len(candidates),
            "bytes": total_bytes,
            "bytes_human": self._format_bytes(total_bytes),
            "filenames": candidates,
        }

    def cleanup_older_than_interactive(self, older_than_days):
        estimate = self.estimate_cleanup_older_than(older_than_days)
        count = int(estimate.get("count") or 0)
        if count <= 0:
            rumps.notification(tr("cleanup.title"), tr("cleanup.nothing_body"), "")
            return False

        confirmed = False
        if self.has_pyobjc and NSAlert is not None:
            alert = NSAlert.alloc().init()
            alert.setMessageText_(tr("cleanup.confirm_title"))
            alert.setInformativeText_(
                tr(
                    "cleanup.confirm_body",
                    days=int(older_than_days),
                    count=count,
                    size=str(estimate.get("bytes_human") or "0 B"),
                )
            )
            try:
                alert.setAlertStyle_(NSAlertStyleWarning)
            except Exception:
                pass
            alert.addButtonWithTitle_(tr("cleanup.confirm_button"))
            alert.addButtonWithTitle_(tr("common.cancel"))
            confirmed = (alert.runModal() == 1000)
        else:
            confirmed = bool(
                rumps.alert(
                    tr("cleanup.confirm_title"),
                    tr(
                        "cleanup.confirm_fallback_body",
                        days=int(older_than_days),
                        count=count,
                        size=str(estimate.get("bytes_human") or "0 B"),
                    ),
                )
            )
        if not confirmed:
            return False

        removed_count = 0
        removed_bytes = 0
        failed = []
        for filename in estimate.get("filenames") or []:
            if self._is_recording_locked_for_edit(filename):
                failed.append(filename)
                continue
            paths = self._paths_for_recording(filename)
            file_failed = False
            removed_any = False
            removed_size_this = 0
            for path in paths.values():
                if not os.path.exists(path):
                    continue
                try:
                    removed_size_this += int(os.path.getsize(path))
                except Exception:
                    pass
                try:
                    os.remove(path)
                    removed_any = True
                except Exception:
                    file_failed = True
            if removed_any:
                removed_count += 1
                removed_bytes += removed_size_this
                self._unhide_recording_entry(filename)
                imported = self._get_imported_recordings()
                if filename in imported:
                    imported.remove(filename)
                    self._set_imported_recordings(imported)
            if file_failed:
                failed.append(filename)

        if removed_count > 0:
            rumps.notification(
                tr("cleanup.done_title"),
                tr("cleanup.done_body", count=removed_count, size=self._format_bytes(removed_bytes)),
                "",
            )
        if failed:
            rumps.alert(tr("cleanup.error_title"), "\n".join(failed[:12]))

        self.app.request_ui_refresh()
        return removed_count > 0 and not failed

    def _get_hidden_recordings(self):
        raw = self.app.config.get("hidden_recordings", [])
        if isinstance(raw, list):
            return set(str(x) for x in raw if isinstance(x, str) and x)
        return set()

    def _set_hidden_recordings(self, hidden_set):
        self.app.config["hidden_recordings"] = sorted(hidden_set)
        ConfigManager.save(self.app.config)

    def _get_imported_recordings(self):
        raw = self.app.config.get("imported_recordings", [])
        if isinstance(raw, list):
            return set(str(x) for x in raw if isinstance(x, str) and x)
        return set()

    def _set_imported_recordings(self, imported_set):
        self.app.config["imported_recordings"] = sorted(imported_set)
        ConfigManager.save(self.app.config)

    def is_imported_recording(self, filename):
        return bool(filename and filename in self._get_imported_recordings())

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
        active_recording_name = os.path.basename(self.app.current_filename) if self.app.current_filename else None
        if self.app.is_recording and active_recording_name == filename:
            rumps.alert(tr("blocked.title"), tr("blocked.recording"))
            return True
        if self.app.current_processing_file == filename:
            rumps.alert(tr("blocked.title"), tr("blocked.processing"))
            return True
        return False

    def _sanitize_recording_base_name(self, raw_name):
        name = (raw_name or "").strip()
        root, ext = os.path.splitext(name)
        if ext:
            name = root.strip()
        name = name.replace("/", " ").replace(":", "-")
        name = re.sub(r"\s+", " ", name).strip().strip(".")
        return name

    def _build_unique_filename(self, base_name, extension):
        ext = str(extension or "").lower()
        if not ext.startswith("."):
            ext = "." + ext
        candidate = f"{base_name}{ext}"
        save_dir = self.app.config["save_dir"]
        if not os.path.exists(os.path.join(save_dir, candidate)):
            return candidate
        idx = 2
        while True:
            candidate = f"{base_name}_{idx}{ext}"
            if not os.path.exists(os.path.join(save_dir, candidate)):
                return candidate
            idx += 1

    def import_external_meeting_file(self, source_path):
        """Synchronous import helper kept for internal/background use."""
        src = str(source_path or "").strip()
        if not src or not os.path.isfile(src):
            raise FileNotFoundError(tr("import.error.not_found"))

        ext = os.path.splitext(src)[1].lower()
        if ext not in self.SUPPORTED_MEETING_EXTENSIONS:
            raise ValueError(tr("import.error.unsupported", ext=ext or "?"))

        base = self._sanitize_recording_base_name(os.path.splitext(os.path.basename(src))[0])
        if not base:
            base = "Imported_Meeting"
        target_name = self._build_unique_filename(base, ext)
        target_path = os.path.join(self.app.config["save_dir"], target_name)

        # Fast path: already in save_dir with the same basename.
        if os.path.abspath(src) != os.path.abspath(target_path):
            total = max(1, os.path.getsize(src))
            copied = 0
            last_progress = -1.0
            with open(src, "rb") as in_f, open(target_path, "wb") as out_f:
                while True:
                    chunk = in_f.read(1024 * 1024)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    copied += len(chunk)
                    progress = min(1.0, float(copied) / float(total))
                    if progress - last_progress >= 0.01:
                        last_progress = progress
                        self.app.import_progress = progress
                        self.app.request_ui_refresh()
            try:
                shutil.copystat(src, target_path, follow_symlinks=True)
            except Exception:
                pass
        # Keep imported entries at top of library (sorting is by mtime desc).
        try:
            os.utime(target_path, None)
        except Exception:
            pass
        self._unhide_recording_entry(target_name)
        imported = self._get_imported_recordings()
        imported.add(target_name)
        self._set_imported_recordings(imported)
        return target_name

    def import_external_meeting_file_async(self, source_path, on_done=None):
        src = str(source_path or "").strip()
        if self.app.is_importing:
            rumps.alert(tr("import.error.title"), tr("import.error.busy"))
            return False

        def worker():
            imported_name = None
            error_text = None
            try:
                imported_name = self.import_external_meeting_file(src)
            except Exception as e:
                error_text = str(e) or tr("import.error.copy_failed", error=e)
            finally:
                def finish_ui():
                    self.app.is_importing = False
                    self.app.import_progress = 0.0
                    self.app.current_import_file = None
                    if imported_name:
                        rumps.notification(tr("import.success.title"), tr("import.success.body"), imported_name)
                    elif error_text:
                        rumps.alert(tr("import.error.title"), error_text)
                    self.app.request_ui_refresh()
                    if on_done is not None:
                        try:
                            on_done(imported_name)
                        except Exception:
                            pass

                self.app.run_on_main(finish_ui)

        self.app.is_importing = True
        self.app.import_progress = 0.0
        self.app.current_import_file = os.path.basename(src) if src else None
        self.app.request_ui_refresh()
        threading.Thread(target=worker, daemon=True).start()
        return True

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
        return self.rename_recording(filename, result.text)

    def rename_recording(self, filename, raw_new_name):
        if not filename:
            return None
        if self._is_recording_locked_for_edit(filename):
            return None

        current_base = os.path.splitext(filename)[0]
        new_base = self._sanitize_recording_base_name(raw_new_name)
        if not new_base:
            rumps.alert(tr("rename.error_title"), tr("rename.error_empty"))
            return None
        if new_base == current_base:
            return filename

        old_ext = os.path.splitext(filename)[1] or ".mp4"
        new_filename = f"{new_base}{old_ext}"
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
        if os.path.exists(old_paths["protocol_meta"]):
            rename_ops.append((old_paths["protocol_meta"], new_paths["protocol_meta"]))

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

        imported = self._get_imported_recordings()
        if filename in imported:
            imported.remove(filename)
            imported.add(new_filename)
            self._set_imported_recordings(imported)

        rumps.notification(tr("rename.done_title"), tr("rename.done_body"), new_filename)
        self.app.request_ui_refresh()
        return new_filename

    def archive_recording_interactive(self, filename):
        if not filename:
            return False
        if self._is_recording_locked_for_edit(filename):
            return False

        confirmed = False
        if self.has_pyobjc and NSAlert is not None:
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
        self.app.request_ui_refresh()
        return True

    def delete_recording_with_files_interactive(self, filename):
        if not filename:
            return False
        if self._is_recording_locked_for_edit(filename):
            return False

        confirmed = False
        if self.has_pyobjc and NSAlert is not None:
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
        to_delete = [paths["video"], paths["mic"], paths["protocol"], paths["protocol_meta"]]

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
        imported = self._get_imported_recordings()
        if filename in imported:
            imported.remove(filename)
            self._set_imported_recordings(imported)
        self.app.request_ui_refresh()
        return not failed

    def delete_processing_result_interactive(self, filename):
        if not filename:
            return False
        if self._is_recording_locked_for_edit(filename):
            return False

        paths = self._paths_for_recording(filename)
        if not os.path.exists(paths["protocol"]) and not os.path.exists(paths["protocol_meta"]):
            return False

        confirmed = False
        if self.has_pyobjc and NSAlert is not None:
            alert = NSAlert.alloc().init()
            alert.setMessageText_(tr("delete_processing_result.confirm_title"))
            alert.setInformativeText_(tr("delete_processing_result.confirm_body", filename=filename))
            try:
                alert.setAlertStyle_(NSAlertStyleWarning)
            except Exception:
                pass
            alert.addButtonWithTitle_(tr("delete_processing_result.confirm_button"))
            alert.addButtonWithTitle_(tr("common.cancel"))
            confirmed = (alert.runModal() == 1000)
        else:
            confirmed = bool(
                rumps.alert(
                    tr("delete_processing_result.confirm_title"),
                    tr("delete_processing_result.confirm_fallback_body"),
                )
            )
        if not confirmed:
            return False

        removed = []
        failed = []
        for key in ("protocol", "protocol_meta"):
            path = paths[key]
            if not os.path.exists(path):
                continue
            try:
                os.remove(path)
                removed.append(os.path.basename(path))
            except Exception as e:
                failed.append(f"{os.path.basename(path)}: {e}")

        if removed:
            rumps.notification(tr("delete_processing_result.done_title"), tr("delete_processing_result.done_body"), filename)
        if failed:
            rumps.alert(tr("delete_processing_result.error_title"), "\n".join(failed))

        self.app.request_ui_refresh()
        return not failed

    # Compatibility alias for older call sites.
    def delete_recording_interactive(self, filename):
        return self.delete_recording_with_files_interactive(filename)
