import os

import objc
from AppKit import NSColor
from Foundation import NSIndexSet

from steno.i18n import tr


class MainWindowStateMixin:
    @objc.python_method
    def _estimate_prompt_height(self):
        minimum = 120.0
        maximum = 320.0
        try:
            self.prompt_text.layoutManager().glyphRangeForTextContainer_(self.prompt_text.textContainer())
            used = self.prompt_text.layoutManager().usedRectForTextContainer_(self.prompt_text.textContainer())
            estimated = float(used.size.height) + 18.0
            return max(minimum, min(maximum, estimated))
        except Exception:
            try:
                text = str(self.prompt_text.string() or "")
                lines = max(1, len(text.splitlines()))
                estimated = 18.0 + lines * 18.0
                return max(minimum, min(maximum, estimated))
            except Exception:
                return minimum

    @objc.python_method
    def _apply_dynamic_detail_layout(self, status):
        root_w, root_h = self.content_view.bounds()[1]
        content_w = max(320.0, root_w)
        pad = 24.0
        full_w = content_w - (pad * 2.0)
        bottom_pad = 24.0

        title_h = 28.0
        files_h = 54.0
        controls_h = 30.0
        prompt_label_h = 24.0
        hint_h = 18.0
        info_h = 58.0

        # Top-down flow layout to avoid \"nailed\" look.
        cursor_top = root_h - 24.0

        title_y = cursor_top - title_h
        self.detail_title_label.setFrame_(((pad, title_y), (760.0, title_h)))
        cursor_top = title_y - 10.0

        files_y = cursor_top - files_h
        self.files_label.setFrame_(((pad, files_y), (820.0, files_h)))
        cursor_top = files_y

        if status == "unprocessed":
            # tighter gap between files and prompt
            cursor_top -= 8.0
            prompt_label_y = cursor_top - prompt_label_h
            self.prompt_label.setFrame_(((pad, prompt_label_y), (260.0, prompt_label_h)))
            cursor_top = prompt_label_y - 6.0

            prompt_h = self._estimate_prompt_height()
            prompt_y = cursor_top - prompt_h
            self.prompt_scroll.setFrame_(((pad, prompt_y), (full_w, prompt_h)))
            cursor_top = prompt_y - 4.0

            hint_y = cursor_top - hint_h
            self.prompt_hint_label.setFrame_(((pad, hint_y), (full_w, hint_h)))
            cursor_top = hint_y - 8.0

            # \"No protocol yet\" message area
            protocol_y = cursor_top - info_h
            self.protocol_scroll.setFrame_(((pad, protocol_y), (full_w, info_h)))
            cursor_top = protocol_y - 8.0

            # Process button below \"No protocol yet\" text
            controls_y = max(bottom_pad, cursor_top - controls_h)
            self.process_button.setFrame_(((pad, controls_y), (140.0, controls_h)))
            self.loader.setFrame_(((pad + 150.0, controls_y + 3.0), (24.0, 24.0)))
            self.copy_protocol_button.setFrame_(((pad, controls_y), (140.0, controls_h)))
        else:
            # tighter gap between files and controls
            controls_y = cursor_top - 8.0 - controls_h
            self.process_button.setFrame_(((pad, controls_y), (120.0, controls_h)))
            self.copy_protocol_button.setFrame_(((pad, controls_y), (140.0, controls_h)))
            self.loader.setFrame_(((pad + 132.0, controls_y + 3.0), (24.0, 24.0)))

            # protocol starts right below controls (no excessive blank area)
            protocol_top = controls_y - 8.0
            protocol_h = max(120.0, protocol_top - bottom_pad)
            self.protocol_scroll.setFrame_(((pad, bottom_pad), (full_w, protocol_h)))

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
            self.app.is_recording
            and os.path.basename(self.app.current_filename) == filename
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
            "unprocessed": "○",
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
        self.recording_files = self.app.recordings_service.list_recent_recordings(limit=200)
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
            self._apply_dynamic_detail_layout("none")
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

        # Load draft/config prompt before layout so dynamic textarea height is based on actual text.
        if status == "unprocessed" and self.prompt_loaded_for != video_name:
            prompt_value = self.prompt_drafts.get(video_name)
            if prompt_value is None:
                prompt_value = self.app.config.get("prompt", "")
            self.prompt_text.setString_(prompt_value)
            self.prompt_loaded_for = video_name

        self._apply_dynamic_detail_layout(status)

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
