import os

import rumps
from AppKit import NSApp, NSMenu, NSMenuItem, NSPasteboard, NSPasteboardTypeString
from Foundation import NSIndexSet

from steno.config import AI_MODELS, VIDEO_QUALITY_PRESETS
from steno.i18n import tr


class MainWindowActionsMixin:
    def onStartStop_(self, _):
        self.app.record_switch(None)
        self.refresh_from_state()
        self.refresh_file_lists()
        self.refresh_detail_view()

    def onProcessSelected_(self, _):
        if not self.selected_recording:
            return
        if self._status_for_recording(self.selected_recording) != "unprocessed":
            return
        self._remember_prompt_draft_for_selected()
        final_prompt = self.prompt_drafts.get(self.selected_recording, self.app.config.get("prompt", ""))
        self.app.process_video_file(self.selected_recording, prompt_override=final_prompt)
        self.refresh_from_state()
        self.refresh_file_lists()
        self.refresh_detail_view()

    def onCopyProtocol_(self, _):
        if not self.selected_recording:
            return
        base = os.path.splitext(self.selected_recording)[0]
        protocol_path = os.path.join(self.app.config["save_dir"], base + "_protocol.txt")
        if not os.path.exists(protocol_path):
            rumps.alert(tr("copy.title"), tr("copy.not_ready"))
            return
        try:
            with open(protocol_path, "r", encoding="utf-8") as f:
                text = f.read()
            pasteboard = NSPasteboard.generalPasteboard()
            pasteboard.clearContents()
            pasteboard.setString_forType_(text, NSPasteboardTypeString)
            rumps.notification(
                tr("copy.success_title"),
                tr("copy.success_body"),
                os.path.basename(protocol_path),
            )
        except Exception as e:
            rumps.alert(tr("copy.error_title"), str(e))

    def onContextRename_(self, _):
        if not self.selected_recording:
            return
        old_name = self.selected_recording
        self._remember_prompt_draft_for_selected()
        renamed_to = self.app.recordings_service.rename_recording_interactive(old_name)
        if renamed_to:
            old_draft = self.prompt_drafts.pop(old_name, None)
            if old_draft is not None:
                self.prompt_drafts[renamed_to] = old_draft
            self.selected_recording = renamed_to
            self.prompt_loaded_for = None
        self.refresh_from_state()
        self.refresh_file_lists()
        self.refresh_detail_view()

    def onContextArchive_(self, _):
        if not self.selected_recording:
            return
        target = self.selected_recording
        if self.app.recordings_service.archive_recording_interactive(target):
            self.prompt_drafts.pop(target, None)
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
        if self.app.recordings_service.delete_recording_with_files_interactive(target):
            self.prompt_drafts.pop(target, None)
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

        menu.addItem_(NSMenuItem.separatorItem())
        for title, action in [
            (tr("main.set_api_key"), "onSetApiKey:"),
            (tr("main.set_base_url"), "onSetBaseURL:"),
            (tr("main.edit_system_prompt"), "onEditPrompt:"),
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

        NSMenu.popUpContextMenu_withEvent_forView_(menu, NSApp().currentEvent(), sender)

    def onSelectQuality_(self, sender):
        self.app.set_video_quality_value(str(sender.representedObject()))

    def onSelectModel_(self, sender):
        self.app.set_ai_model_value(str(sender.representedObject()))

    def onSetApiKey_(self, _):
        self.app.set_api_key(None)

    def onSetBaseURL_(self, _):
        self.app.set_base_url(None)

    def onEditPrompt_(self, _):
        self.app.edit_prompt(None)

    def onOpenOutput_(self, _):
        self.app.open_folder(None)

    def onResetPermissions_(self, _):
        self.app.reset_permissions(None)

    def onResetPermissionsRestart_(self, _):
        self.app.reset_permissions_and_restart(None)

    def onOpenLink_(self, _):
        self.app.open_link(None)

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
