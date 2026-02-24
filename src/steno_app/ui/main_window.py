import objc
from Foundation import NSObject

from steno_app.ui.main_window_actions import MainWindowActionsMixin
from steno_app.ui.main_window_state import MainWindowStateMixin
from steno_app.ui.main_window_view import MainWindowViewMixin


class MainWindowController(
    NSObject,
    MainWindowActionsMixin,
    MainWindowStateMixin,
    MainWindowViewMixin,
):
    def initWithApp_(self, app):
        self = objc.super(MainWindowController, self).init()
        if self:
            self.app = app
            self.recording_files = []
            self.selected_recording = None
            self.prompt_drafts = {}
            self.user_prompt_drafts = {}
            self.template_id_drafts = {}
            self.prompt_loaded_for = None
            self.video_duration_cache = {}
            self.inline_rename_row = None
            self.inline_rename_filename = None
            self.inline_rename_field = None
            self.inline_rename_in_commit = False
            self.build_window()
        return self

    # Expose ObjC selectors directly on the NSObject subclass so AppKit reliably sees them.
    def windowDidResize_(self, obj):
        return MainWindowViewMixin.windowDidResize_(self, obj)

    def windowWillClose_(self, obj):
        return MainWindowViewMixin.windowWillClose_(self, obj)

    def menuWillOpen_(self, menu):
        return MainWindowActionsMixin.menuWillOpen_(self, menu)

    def numberOfRowsInTableView_(self, table):
        return MainWindowStateMixin.numberOfRowsInTableView_(self, table)

    def tableView_objectValueForTableColumn_row_(self, table, column, row):
        return MainWindowStateMixin.tableView_objectValueForTableColumn_row_(self, table, column, row)

    def tableView_viewForTableColumn_row_(self, table, column, row):
        return MainWindowStateMixin.tableView_viewForTableColumn_row_(self, table, column, row)

    def tableView_shouldEditTableColumn_row_(self, table, column, row):
        return MainWindowStateMixin.tableView_shouldEditTableColumn_row_(self, table, column, row)

    def tableView_setObjectValue_forTableColumn_row_(self, table, value, column, row):
        return MainWindowStateMixin.tableView_setObjectValue_forTableColumn_row_(self, table, value, column, row)

    def tableViewSelectionDidChange_(self, notification):
        return MainWindowStateMixin.tableViewSelectionDidChange_(self, notification)

    def tableView_rowViewForRow_(self, table, row):
        return MainWindowStateMixin.tableView_rowViewForRow_(self, table, row)

    def controlTextDidEndEditing_(self, notification):
        return MainWindowStateMixin.controlTextDidEndEditing_(self, notification)

    def onStartStop_(self, obj):
        return MainWindowActionsMixin.onStartStop_(self, obj)

    def onImportMeeting_(self, obj):
        return MainWindowActionsMixin.onImportMeeting_(self, obj)

    def onProcessSelected_(self, obj):
        return MainWindowActionsMixin.onProcessSelected_(self, obj)

    def onPromptTemplateChanged_(self, obj):
        return MainWindowActionsMixin.onPromptTemplateChanged_(self, obj)

    def onCopyProtocol_(self, obj):
        return MainWindowActionsMixin.onCopyProtocol_(self, obj)

    def onCopyProtocolMarkdown_(self, obj):
        return MainWindowActionsMixin.onCopyProtocolMarkdown_(self, obj)

    def onCopyProtocolRendered_(self, obj):
        return MainWindowActionsMixin.onCopyProtocolRendered_(self, obj)

    def onDeleteProcessingResult_(self, obj):
        return MainWindowActionsMixin.onDeleteProcessingResult_(self, obj)

    def onContextRename_(self, obj):
        return MainWindowActionsMixin.onContextRename_(self, obj)

    def onContextArchive_(self, obj):
        return MainWindowActionsMixin.onContextArchive_(self, obj)

    def onContextDeleteProcessingResult_(self, obj):
        return MainWindowActionsMixin.onContextDeleteProcessingResult_(self, obj)

    def onContextDelete_(self, obj):
        return MainWindowActionsMixin.onContextDelete_(self, obj)

    def onOpenSettings_(self, obj):
        return MainWindowActionsMixin.onOpenSettings_(self, obj)

    def onCleanupFiles_(self, obj):
        return MainWindowActionsMixin.onCleanupFiles_(self, obj)

    def onSelectQuality_(self, obj):
        return MainWindowActionsMixin.onSelectQuality_(self, obj)

    def onSelectModel_(self, obj):
        return MainWindowActionsMixin.onSelectModel_(self, obj)

    def onSelectAudioInput_(self, obj):
        return MainWindowActionsMixin.onSelectAudioInput_(self, obj)

    def onCleanupOlderThan_(self, obj):
        return MainWindowActionsMixin.onCleanupOlderThan_(self, obj)

    def onSelectPromptTemplate_(self, obj):
        return MainWindowActionsMixin.onSelectPromptTemplate_(self, obj)

    def onCreatePromptTemplate_(self, obj):
        return MainWindowActionsMixin.onCreatePromptTemplate_(self, obj)

    def onEditPromptTemplate_(self, obj):
        return MainWindowActionsMixin.onEditPromptTemplate_(self, obj)

    def onArchivePromptTemplate_(self, obj):
        return MainWindowActionsMixin.onArchivePromptTemplate_(self, obj)

    def onRestorePromptTemplate_(self, obj):
        return MainWindowActionsMixin.onRestorePromptTemplate_(self, obj)

    def onDeletePromptTemplate_(self, obj):
        return MainWindowActionsMixin.onDeletePromptTemplate_(self, obj)

    def onSetApiKey_(self, obj):
        return MainWindowActionsMixin.onSetApiKey_(self, obj)

    def onSetBaseURL_(self, obj):
        return MainWindowActionsMixin.onSetBaseURL_(self, obj)

    def onEditPrompt_(self, obj):
        return MainWindowActionsMixin.onEditPrompt_(self, obj)

    def onOpenOutput_(self, obj):
        return MainWindowActionsMixin.onOpenOutput_(self, obj)

    def onOpenLink_(self, obj):
        return MainWindowActionsMixin.onOpenLink_(self, obj)

    def onRecordingsDoubleClick_(self, obj):
        return MainWindowActionsMixin.onRecordingsDoubleClick_(self, obj)
