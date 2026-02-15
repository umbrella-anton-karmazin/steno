import os
import re
import time

import rumps
from AppKit import NSApp, NSMenu, NSMenuItem, NSOpenPanel, NSPasteboard, NSPasteboardTypeString
from Foundation import NSIndexSet

from steno_app.config import (
    AI_MODELS,
    VIDEO_QUALITY_PRESETS,
    ConfigManager,
    archive_prompt_template,
    delete_prompt_template,
    get_prompt_template_by_id,
    get_prompt_templates,
    get_selected_prompt_template,
    set_selected_prompt_template,
    upsert_prompt_template,
)
from steno_app.i18n import tr


class MainWindowActionsMixin:
    def _template_display_name(self, template, include_builtin_marker=False):
        template_id = str((template or {}).get("id") or "")
        built_in = bool((template or {}).get("built_in"))
        name_key = {
            "meeting_protocol": "prompt.template.meeting_protocol",
            "meeting_transcript": "prompt.template.meeting_transcript",
            "meeting_analysis": "prompt.template.meeting_analysis",
        }.get(template_id)
        name = tr(name_key) if name_key else str((template or {}).get("name") or template_id or "")
        if include_builtin_marker and built_in:
            return f"{name} ({tr('prompt.template.built_in')})"
        return name

    def _slugify_template_id(self, name):
        slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
        if not slug:
            slug = f"custom_{int(time.time())}"
        if not slug.startswith("custom_"):
            slug = "custom_" + slug
        return slug

    def _refresh_after_template_change(self):
        # Settings actions must not directly overwrite prompt editor content in main view.
        if self.selected_recording and self._status_for_recording(self.selected_recording) == "unprocessed":
            self.prompt_drafts[self.selected_recording] = self._current_prompt_text()
            self.user_prompt_drafts[self.selected_recording] = self._current_user_prompt_text()
            current_template_id = self.template_id_drafts.get(self.selected_recording) or self._selected_template_id_from_popup()
            if current_template_id:
                self.template_id_drafts[self.selected_recording] = current_template_id
        if self.window:
            self.refresh_from_state()
            self.refresh_file_lists()
            self.refresh_detail_view()

    def onStartStop_(self, _):
        self.app.record_switch(None)
        self.refresh_from_state()
        self.refresh_file_lists()
        self.refresh_detail_view()

    def onImportMeeting_(self, _):
        if getattr(self.app, "is_importing", False):
            rumps.alert(tr("import.error.title"), tr("import.error.busy"))
            return
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(
            [
                "mp4",
                "mov",
                "m4v",
                "mkv",
                "webm",
                "avi",
                "m4a",
                "mp3",
                "wav",
                "aac",
                "flac",
                "ogg",
            ]
        )
        response = panel.runModal()
        if int(response) != 1:
            return

        try:
            src_path = str(panel.URL().path() or "")
        except Exception:
            src_path = ""
        if not src_path:
            return

        def on_done(imported_name):
            if imported_name:
                self.focus_recording(imported_name)

        self.app.meetings_service.import_external_meeting_file_async(src_path, on_done=on_done)

    def onProcessSelected_(self, _):
        if not self.selected_recording:
            return
        if self._status_for_recording(self.selected_recording) != "unprocessed":
            return
        self._remember_prompt_draft_for_selected()
        final_system_prompt = self.prompt_drafts.get(self.selected_recording, self.app.config.get("prompt", ""))
        final_user_prompt = self.user_prompt_drafts.get(self.selected_recording, "")
        final_template_id = self.template_id_drafts.get(self.selected_recording) or self._selected_template_id_from_popup()
        self.app.process_video_file(
            self.selected_recording,
            system_prompt_override=final_system_prompt,
            user_prompt_override=final_user_prompt,
            template_id_override=final_template_id,
        )
        self.refresh_from_state()
        self.refresh_file_lists()
        self.refresh_detail_view()

    def onPromptTemplateChanged_(self, _):
        template_id = self._selected_template_id_from_popup()
        self.apply_prompt_template_for_selected(template_id)

    def _protocol_path_for_selected(self):
        if not self.selected_recording:
            return None
        base = os.path.splitext(self.selected_recording)[0]
        return os.path.join(self.app.config["save_dir"], base + "_protocol.txt")

    def _read_selected_protocol(self):
        protocol_path = self._protocol_path_for_selected()
        if not protocol_path or not os.path.exists(protocol_path):
            return None, None
        try:
            with open(protocol_path, "r", encoding="utf-8") as f:
                return protocol_path, f.read()
        except Exception as e:
            rumps.alert(tr("copy.error_title"), str(e))
            return None, None

    def _copy_to_clipboard(self, text):
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, NSPasteboardTypeString)

    def _markdown_to_rendered_text(self, text):
        lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        out = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                out.append("")
                i += 1
                continue

            if self._is_table_line(line):
                block = []
                j = i
                while j < len(lines) and self._is_table_line(lines[j]):
                    block.append(lines[j])
                    j += 1
                rows = [self._split_table_row(x) for x in block]
                rows = [r for r in rows if r]
                for row in rows:
                    if self._is_table_separator_row(row):
                        continue
                    out.append(" | ".join(c.strip() for c in row))
                i = j
                continue

            if stripped.startswith("#"):
                heading = stripped.lstrip("#").strip()
                out.append(heading)
                i += 1
                continue

            if stripped.startswith("* "):
                out.append("• " + stripped[2:].strip())
                i += 1
                continue

            out.append(stripped)
            i += 1

        result = "\n".join(out)
        # Remove basic markdown emphasis markers in copied plain text.
        result = result.replace("**", "").replace("__", "")
        return result

    def onCopyProtocol_(self, sender):
        protocol_path = self._protocol_path_for_selected()
        if not protocol_path or not os.path.exists(protocol_path):
            rumps.alert(tr("copy.title"), tr("copy.not_ready"))
            return

        menu = NSMenu.alloc().initWithTitle_(tr("copy.title"))
        copy_md_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("copy.as_markdown"), "onCopyProtocolMarkdown:", "")
        copy_md_item.setTarget_(self)
        menu.addItem_(copy_md_item)

        copy_rendered_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("copy.as_rendered"), "onCopyProtocolRendered:", "")
        copy_rendered_item.setTarget_(self)
        menu.addItem_(copy_rendered_item)

        NSMenu.popUpContextMenu_withEvent_forView_(menu, NSApp().currentEvent(), sender)

    def onCopyProtocolMarkdown_(self, _):
        protocol_path, markdown = self._read_selected_protocol()
        if not protocol_path:
            rumps.alert(tr("copy.title"), tr("copy.not_ready"))
            return
        self._copy_to_clipboard(markdown)
        rumps.notification(
            tr("copy.success_title"),
            tr("copy.success_body_markdown"),
            os.path.basename(protocol_path),
        )

    def onCopyProtocolRendered_(self, _):
        protocol_path, markdown = self._read_selected_protocol()
        if not protocol_path:
            rumps.alert(tr("copy.title"), tr("copy.not_ready"))
            return
        rendered_text = self._markdown_to_rendered_text(markdown)
        self._copy_to_clipboard(rendered_text)
        rumps.notification(
            tr("copy.success_title"),
            tr("copy.success_body_rendered"),
            os.path.basename(protocol_path),
        )

    def onContextRename_(self, _):
        self.start_inline_rename_for_selected()

    def onContextArchive_(self, _):
        if not self.selected_recording:
            return
        target = self.selected_recording
        if self.app.meetings_service.archive_recording_interactive(target):
            self.prompt_drafts.pop(target, None)
            self.user_prompt_drafts.pop(target, None)
            self.template_id_drafts.pop(target, None)
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
        if self.app.meetings_service.delete_recording_with_files_interactive(target):
            self.prompt_drafts.pop(target, None)
            self.user_prompt_drafts.pop(target, None)
            self.template_id_drafts.pop(target, None)
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

        templates_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.prompt_templates_manage"), None, "")
        templates_submenu = NSMenu.alloc().initWithTitle_(tr("main.prompt_templates_manage"))
        selected_template = get_selected_prompt_template(self.app.config) or {}
        selected_template_id = str(selected_template.get("id") or "")
        active_templates = get_prompt_templates(self.app.config, include_archived=False)
        for template in active_templates:
            template_id = str(template.get("id") or "")
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                self._template_display_name(template, include_builtin_marker=True),
                "onSelectPromptTemplate:",
                "",
            )
            item.setTarget_(self)
            item.setRepresentedObject_(template_id)
            item.setState_(1 if template_id == selected_template_id else 0)
            templates_submenu.addItem_(item)

        templates_submenu.addItem_(NSMenuItem.separatorItem())

        create_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.prompt_templates_create"), "onCreatePromptTemplate:", "")
        create_item.setTarget_(self)
        templates_submenu.addItem_(create_item)

        edit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.prompt_templates_edit"), "onEditPromptTemplate:", "")
        edit_item.setTarget_(self)
        edit_item.setRepresentedObject_(selected_template_id)
        edit_item.setEnabled_(bool(selected_template_id))
        templates_submenu.addItem_(edit_item)

        archive_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.prompt_templates_archive"), "onArchivePromptTemplate:", "")
        archive_item.setTarget_(self)
        archive_item.setRepresentedObject_(selected_template_id)
        archive_item.setEnabled_(bool(selected_template_id and len(active_templates) > 1))
        templates_submenu.addItem_(archive_item)

        delete_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.prompt_templates_delete"), "onDeletePromptTemplate:", "")
        delete_item.setTarget_(self)
        delete_item.setRepresentedObject_(selected_template_id)
        selected_built_in = bool(selected_template.get("built_in"))
        delete_item.setEnabled_(bool(selected_template_id) and not selected_built_in)
        templates_submenu.addItem_(delete_item)

        archived_templates = [t for t in get_prompt_templates(self.app.config, include_archived=True) if t.get("archived")]
        if archived_templates:
            templates_submenu.addItem_(NSMenuItem.separatorItem())
            archived_title_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.prompt_templates_archived"), None, "")
            archived_title_item.setEnabled_(False)
            templates_submenu.addItem_(archived_title_item)
            for template in archived_templates:
                restore_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    tr("main.prompt_templates_restore_named", name=self._template_display_name(template, include_builtin_marker=True)),
                    "onRestorePromptTemplate:",
                    "",
                )
                restore_item.setTarget_(self)
                restore_item.setRepresentedObject_(str(template.get("id") or ""))
                templates_submenu.addItem_(restore_item)

        templates_item.setSubmenu_(templates_submenu)
        menu.addItem_(templates_item)

        menu.addItem_(NSMenuItem.separatorItem())
        for title, action in [
            (tr("main.set_api_key"), "onSetApiKey:"),
            (tr("main.set_base_url"), "onSetBaseURL:"),
            (tr("main.open_output_folder"), "onOpenOutput:"),
        ]:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            item.setTarget_(self)
            menu.addItem_(item)

        menu.addItem_(NSMenuItem.separatorItem())
        usage_last = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            tr("menu.tokens_last", value=self.app.config.get("last_request_tokens", 0)),
            None,
            "",
        )
        usage_last.setEnabled_(False)
        usage_total = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            tr("menu.tokens_used", value=self.app.config.get("used_tokens", 0)),
            None,
            "",
        )
        usage_total.setEnabled_(False)
        menu.addItem_(usage_last)
        menu.addItem_(usage_total)

        menu.addItem_(NSMenuItem.separatorItem())
        made_by_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("menu.made_by"), "onOpenLink:", "")
        made_by_item.setTarget_(self)
        menu.addItem_(made_by_item)

        NSMenu.popUpContextMenu_withEvent_forView_(menu, NSApp().currentEvent(), sender)

    def onSelectQuality_(self, sender):
        self.app.set_video_quality_value(str(sender.representedObject()))

    def onSelectModel_(self, sender):
        self.app.set_ai_model_value(str(sender.representedObject()))

    def onSelectPromptTemplate_(self, sender):
        template_id = str(sender.representedObject() or "")
        if not template_id:
            return
        if not set_selected_prompt_template(self.app.config, template_id):
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_select_failed"))
            return
        ConfigManager.save(self.app.config)
        # Do not apply from settings directly to currently opened prompt fields.
        self._refresh_after_template_change()

    def onCreatePromptTemplate_(self, _):
        name_win = rumps.Window(
            tr("dialog.prompt_template.name_title"),
            tr("dialog.prompt_template.name_hint"),
            "",
            dimensions=(520, 50),
        )
        name_result = name_win.run()
        if not name_result.clicked:
            return
        name = (name_result.text or "").strip()
        if not name:
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_name_required"))
            return

        system_win = rumps.Window(
            tr("dialog.prompt_template.system_title"),
            tr("dialog.prompt_template.system_hint"),
            "",
            dimensions=(700, 220),
        )
        system_result = system_win.run()
        if not system_result.clicked:
            return
        system_prompt = (system_result.text or "").strip()
        if not system_prompt:
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_system_required"))
            return

        user_win = rumps.Window(
            tr("dialog.prompt_template.user_title"),
            tr("dialog.prompt_template.user_hint"),
            "",
            dimensions=(700, 140),
        )
        user_result = user_win.run()
        if not user_result.clicked:
            return
        user_prompt = (user_result.text or "").strip()

        template_id = self._slugify_template_id(name)
        existing_ids = {str(t.get("id") or "") for t in get_prompt_templates(self.app.config, include_archived=True)}
        if template_id in existing_ids:
            template_id = f"{template_id}_{int(time.time())}"

        upsert_prompt_template(
            self.app.config,
            {
                "id": template_id,
                "name": name,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "built_in": False,
                "archived": False,
            },
        )
        set_selected_prompt_template(self.app.config, template_id)
        ConfigManager.save(self.app.config)
        self._refresh_after_template_change()

    def onEditPromptTemplate_(self, sender):
        template_id = str(sender.representedObject() or "") or str((get_selected_prompt_template(self.app.config) or {}).get("id") or "")
        template = get_prompt_template_by_id(self.app.config, template_id)
        if not template:
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_not_found"))
            return
        selected_id = str((self.app.config.get("prompt_templates") or {}).get("selected_template_id") or "")

        name_win = rumps.Window(
            tr("dialog.prompt_template.name_title"),
            tr("dialog.prompt_template.name_hint"),
            str(template.get("name") or ""),
            dimensions=(520, 50),
        )
        name_result = name_win.run()
        if not name_result.clicked:
            return
        name = (name_result.text or "").strip()
        if not name:
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_name_required"))
            return

        system_win = rumps.Window(
            tr("dialog.prompt_template.system_title"),
            tr("dialog.prompt_template.system_hint"),
            str(template.get("system_prompt") or ""),
            dimensions=(700, 220),
        )
        system_result = system_win.run()
        if not system_result.clicked:
            return
        system_prompt = (system_result.text or "").strip()
        if not system_prompt:
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_system_required"))
            return

        user_win = rumps.Window(
            tr("dialog.prompt_template.user_title"),
            tr("dialog.prompt_template.user_hint"),
            str(template.get("user_prompt") or ""),
            dimensions=(700, 140),
        )
        user_result = user_win.run()
        if not user_result.clicked:
            return
        user_prompt = (user_result.text or "").strip()

        upsert_prompt_template(
            self.app.config,
            {
                "id": template_id,
                "name": name,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "built_in": bool(template.get("built_in")),
                "archived": bool(template.get("archived")),
            },
        )
        # Do not switch active template during edit.
        # If edited template is already active, refresh legacy single-prompt mirror.
        if template_id == selected_id:
            self.app.config["prompt"] = system_prompt
        ConfigManager.save(self.app.config)
        self._refresh_after_template_change()

    def onArchivePromptTemplate_(self, sender):
        template_id = str(sender.representedObject() or "")
        if not template_id:
            return
        active_templates = get_prompt_templates(self.app.config, include_archived=False)
        if len(active_templates) <= 1:
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_keep_one"))
            return
        if archive_prompt_template(self.app.config, template_id, archived=True):
            ConfigManager.save(self.app.config)
            self._refresh_after_template_change()
        else:
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_archive_failed"))

    def onRestorePromptTemplate_(self, sender):
        template_id = str(sender.representedObject() or "")
        if not template_id:
            return
        if archive_prompt_template(self.app.config, template_id, archived=False):
            set_selected_prompt_template(self.app.config, template_id)
            ConfigManager.save(self.app.config)
            self._refresh_after_template_change()
        else:
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_restore_failed"))

    def onDeletePromptTemplate_(self, sender):
        template_id = str(sender.representedObject() or "")
        if not template_id:
            return
        template = get_prompt_template_by_id(self.app.config, template_id)
        if not template:
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_not_found"))
            return
        if template.get("built_in"):
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_delete_builtin"))
            return
        if delete_prompt_template(self.app.config, template_id):
            ConfigManager.save(self.app.config)
            self._refresh_after_template_change()
        else:
            rumps.alert(tr("prompt_templates.error_title"), tr("prompt_templates.error_delete_failed"))

    def onSetApiKey_(self, _):
        self.app.set_api_key(None)

    def onSetBaseURL_(self, _):
        self.app.set_base_url(None)

    def onEditPrompt_(self, _):
        self.app.edit_prompt(None)

    def onOpenOutput_(self, _):
        self.app.open_folder(None)

    def onOpenLink_(self, _):
        self.app.open_link(None)

    def onRecordingsDoubleClick_(self, _):
        row = self.recordings_table.clickedRow()
        if row < 0:
            row = self.recordings_table.selectedRow()
        if row < 0:
            return
        self.start_inline_rename_for_row(row)

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
