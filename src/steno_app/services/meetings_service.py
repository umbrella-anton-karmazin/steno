import os
import re

import rumps

from steno_app.config import ConfigManager
from steno_app.i18n import tr


try:
    from AppKit import NSAlert, NSAlertStyleWarning
except Exception:
    NSAlert = None
    NSAlertStyleWarning = None


class MeetingsService:
    def __init__(self, app, has_pyobjc):
        self.app = app
        self.has_pyobjc = bool(has_pyobjc)

    def list_recent_recordings(self, limit=10):
        save_dir = self.app.config["save_dir"]
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

    def _get_hidden_recordings(self):
        raw = self.app.config.get("hidden_recordings", [])
        if isinstance(raw, list):
            return set(str(x) for x in raw if isinstance(x, str) and x)
        return set()

    def _set_hidden_recordings(self, hidden_set):
        self.app.config["hidden_recordings"] = sorted(hidden_set)
        ConfigManager.save(self.app.config)

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
        self.app.request_ui_refresh()
        return not failed

    # Compatibility alias for older call sites.
    def delete_recording_interactive(self, filename):
        return self.delete_recording_with_files_interactive(filename)
