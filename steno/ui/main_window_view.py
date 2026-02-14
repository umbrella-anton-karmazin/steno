import objc
import rumps
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSFont,
    NSMenu,
    NSMenuItem,
    NSProgressIndicator,
    NSScrollView,
    NSTableColumn,
    NSTableView,
    NSTextField,
    NSTextView,
    NSView,
    NSViewHeightSizable,
    NSViewMaxXMargin,
    NSViewMaxYMargin,
    NSViewMinYMargin,
    NSViewMinXMargin,
    NSViewWidthSizable,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)

from steno.i18n import tr


class MainWindowViewMixin:
    @objc.python_method
    def _label(self, frame, text, bold=False, secondary=False):
        label = NSTextField.alloc().initWithFrame_(frame)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setStringValue_(text)
        if bold:
            label.setFont_(NSFont.boldSystemFontOfSize_(13.0))
        elif secondary:
            label.setFont_(NSFont.systemFontOfSize_(12.0))
            label.setTextColor_(NSColor.secondaryLabelColor())
        return label

    @objc.python_method
    def _button(self, frame, title, action, bordered=True):
        button = NSButton.alloc().initWithFrame_(frame)
        button.setTitle_(title)
        button.setTarget_(self)
        button.setAction_(action)
        button.setBordered_(bordered)
        if bordered:
            button.setBezelStyle_(NSBezelStyleRounded)
        return button

    @objc.python_method
    def build_window(self):
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable
        )
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((220.0, 120.0), (1120.0, 760.0)),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setDelegate_(self)
        self.window.setTitle_(tr("main.window_title"))
        self.window.setMinSize_((920.0, 560.0))
        self.window.setMovableByWindowBackground_(False)

        root = self.window.contentView()
        self.sidebar_width = 300.0
        self.sidebar_view = NSView.alloc().initWithFrame_(((0.0, 0.0), (self.sidebar_width, root.bounds()[1][1])))
        self.sidebar_view.setAutoresizingMask_(NSViewHeightSizable | NSViewMaxXMargin)
        self.sidebar_view.setWantsLayer_(True)
        self.sidebar_view.layer().setBackgroundColor_(NSColor.windowBackgroundColor().CGColor())
        root.addSubview_(self.sidebar_view)

        self.content_view = NSView.alloc().initWithFrame_(((self.sidebar_width, 0.0), (root.bounds()[1][0] - self.sidebar_width, root.bounds()[1][1])))
        self.content_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.content_view.setWantsLayer_(True)
        self.content_view.layer().setBackgroundColor_(NSColor.textBackgroundColor().CGColor())
        root.addSubview_(self.content_view)

        self.start_stop_button = self._button(
            ((16.0, self.sidebar_view.bounds()[1][1] - 46.0), (210.0, 32.0)),
            tr("main.start_recording"),
            "onStartStop:",
        )
        self.start_stop_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
        self.sidebar_view.addSubview_(self.start_stop_button)

        start_button_frame = self.start_stop_button.frame()
        dot_size = 18.0
        dot_x = start_button_frame.origin.x + start_button_frame.size.width + 12.0
        dot_y = start_button_frame.origin.y + ((start_button_frame.size.height - dot_size) / 2.0)
        self.recording_dot_view = NSView.alloc().initWithFrame_(((dot_x, dot_y), (dot_size, dot_size)))
        self.recording_dot_view.setAutoresizingMask_(NSViewMinXMargin | NSViewMinYMargin)
        self.recording_dot_view.setWantsLayer_(True)
        self.recording_dot_view.layer().setCornerRadius_(dot_size / 2.0)
        self.recording_dot_view.setHidden_(True)
        self.sidebar_view.addSubview_(self.recording_dot_view)

        list_top = self.sidebar_view.bounds()[1][1] - 72.0
        list_bottom = 88.0
        self.recordings_scroll = NSScrollView.alloc().initWithFrame_(((8.0, list_bottom), (284.0, max(100.0, list_top - list_bottom))))
        self.recordings_scroll.setHasVerticalScroller_(True)
        self.recordings_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        self.recordings_table = NSTableView.alloc().initWithFrame_(((0.0, 0.0), (284.0, max(100.0, list_top - list_bottom))))
        self.recordings_table.setDelegate_(self)
        self.recordings_table.setDataSource_(self)
        self.recordings_table.setHeaderView_(None)
        self.recordings_table.setUsesAlternatingRowBackgroundColors_(False)
        self.recordings_table.setSelectionHighlightStyle_(0)
        self.recordings_table.setFocusRingType_(1)
        column = NSTableColumn.alloc().initWithIdentifier_("recording")
        column.setWidth_(280.0)
        try:
            column.dataCell().setEditable_(False)
        except Exception:
            pass
        self.recordings_table.addTableColumn_(column)
        self.recordings_scroll.setDocumentView_(self.recordings_table)
        self.sidebar_view.addSubview_(self.recordings_scroll)
        self._build_recordings_context_menu()

        self.settings_button = self._button(((14.0, 30.0), (40.0, 40.0)), "☰", "onOpenSettings:", bordered=False)
        self.settings_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMaxYMargin)
        self.settings_button.setFont_(NSFont.systemFontOfSize_(18.0))
        try:
            self.settings_button.setWantsLayer_(True)
            self.settings_button.layer().setCornerRadius_(10.0)
            self.settings_button.layer().setBackgroundColor_(NSColor.quaternaryLabelColor().colorWithAlphaComponent_(0.2).CGColor())
        except Exception:
            pass
        self.sidebar_view.addSubview_(self.settings_button)

        self.made_by_link = self._button(
            ((62.0, 40.0), (220.0, 22.0)),
            tr("main.made_by"),
            "onOpenLink:",
            bordered=False,
        )
        self.made_by_link.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
        self.made_by_link.setContentTintColor_(NSColor.systemBlueColor())
        self.sidebar_view.addSubview_(self.made_by_link)

        self.detail_title_label = self._label(
            ((24.0, self.content_view.bounds()[1][1] - 52.0), (760.0, 28.0)),
            tr("main.select_recording"),
            bold=True,
        )
        self.detail_title_label.setFont_(NSFont.boldSystemFontOfSize_(20.0))
        self.detail_title_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        self.content_view.addSubview_(self.detail_title_label)

        self.files_label = self._label(
            ((24.0, self.content_view.bounds()[1][1] - 118.0), (820.0, 54.0)),
            tr("main.files_default"),
            secondary=True,
        )
        self.files_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        self.content_view.addSubview_(self.files_label)

        self.process_button = self._button(
            ((24.0, self.content_view.bounds()[1][1] - 160.0), (120.0, 30.0)),
            tr("main.process"),
            "onProcessSelected:",
        )
        self.process_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
        self.content_view.addSubview_(self.process_button)

        self.copy_protocol_button = self._button(
            ((156.0, self.content_view.bounds()[1][1] - 160.0), (140.0, 30.0)),
            tr("main.copy"),
            "onCopyProtocol:",
        )
        self.copy_protocol_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
        self.content_view.addSubview_(self.copy_protocol_button)

        self.loader = NSProgressIndicator.alloc().initWithFrame_(((308.0, self.content_view.bounds()[1][1] - 160.0), (24.0, 24.0)))
        self.loader.setStyle_(0)
        self.loader.setDisplayedWhenStopped_(False)
        self.loader.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
        self.content_view.addSubview_(self.loader)

        self.prompt_label = self._label(
            ((24.0, self.content_view.bounds()[1][1] - 200.0), (260.0, 24.0)),
            tr("main.system_prompt_editable"),
            bold=True,
        )
        self.prompt_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        self.content_view.addSubview_(self.prompt_label)

        self.prompt_scroll = NSScrollView.alloc().initWithFrame_(((24.0, self.content_view.bounds()[1][1] - 334.0), (self.content_view.bounds()[1][0] - 48.0, 120.0)))
        self.prompt_scroll.setHasVerticalScroller_(True)
        self.prompt_scroll.setHasHorizontalScroller_(False)
        self.prompt_scroll.setBorderType_(2)
        self.prompt_scroll.setDrawsBackground_(True)
        self.prompt_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        try:
            self.prompt_scroll.setWantsLayer_(True)
            self.prompt_scroll.layer().setCornerRadius_(6.0)
            self.prompt_scroll.layer().setBorderWidth_(1.0)
            self.prompt_scroll.layer().setBorderColor_(NSColor.quaternaryLabelColor().CGColor())
        except Exception:
            pass
        self.prompt_text = NSTextView.alloc().initWithFrame_(self.prompt_scroll.bounds())
        self.prompt_text.setEditable_(True)
        self.prompt_text.setSelectable_(True)
        self.prompt_text.setRichText_(False)
        self.prompt_text.setFont_(NSFont.systemFontOfSize_(12.0))
        self.prompt_text.setDrawsBackground_(True)
        self.prompt_text.setBackgroundColor_(NSColor.textBackgroundColor())
        self.prompt_scroll.setDocumentView_(self.prompt_text)
        self.content_view.addSubview_(self.prompt_scroll)

        self.prompt_hint_label = self._label(
            ((24.0, self.content_view.bounds()[1][1] - 356.0), (700.0, 18.0)),
            tr("main.prompt_hint"),
            secondary=True,
        )
        self.prompt_hint_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        self.content_view.addSubview_(self.prompt_hint_label)

        self.protocol_scroll = NSScrollView.alloc().initWithFrame_(((24.0, 24.0), (self.content_view.bounds()[1][0] - 48.0, self.content_view.bounds()[1][1] - 396.0)))
        self.protocol_scroll.setHasVerticalScroller_(True)
        self.protocol_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.protocol_text = NSTextView.alloc().initWithFrame_(self.protocol_scroll.bounds())
        self.protocol_text.setEditable_(False)
        self.protocol_text.setSelectable_(True)
        self.protocol_text.setRichText_(False)
        self.protocol_text.setFont_(NSFont.systemFontOfSize_(13.0))
        self.protocol_scroll.setDocumentView_(self.protocol_text)
        self.content_view.addSubview_(self.protocol_scroll)

        self._layout_root_views()
        self.refresh_all()

    @objc.python_method
    def _layout_root_views(self):
        root = self.window.contentView()
        root_width, root_height = root.bounds()[1]
        content_width = max(320.0, root_width - self.sidebar_width)
        self.sidebar_view.setFrame_(((0.0, 0.0), (self.sidebar_width, root_height)))
        self.content_view.setFrame_(((self.sidebar_width, 0.0), (content_width, root_height)))

    @objc.python_method
    def _build_recordings_context_menu(self):
        self.recordings_context_menu = NSMenu.alloc().initWithTitle_(tr("main.recording_context_title"))
        self.recordings_context_menu.setAutoenablesItems_(False)
        self.recordings_context_menu.setDelegate_(self)

        self.ctx_rename_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.ctx_rename"), "onContextRename:", "")
        self.ctx_rename_item.setTarget_(self)
        self.recordings_context_menu.addItem_(self.ctx_rename_item)

        self.ctx_archive_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.ctx_archive"), "onContextArchive:", "")
        self.ctx_archive_item.setTarget_(self)
        self.recordings_context_menu.addItem_(self.ctx_archive_item)

        self.recordings_context_menu.addItem_(NSMenuItem.separatorItem())

        self.ctx_delete_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.ctx_delete"), "onContextDelete:", "")
        self.ctx_delete_item.setTarget_(self)
        self.recordings_context_menu.addItem_(self.ctx_delete_item)

        self.recordings_table.setMenu_(self.recordings_context_menu)

    @objc.python_method
    def _update_recordings_context_menu_state(self):
        has_selected = bool(self.selected_recording and self.selected_recording in self.recording_files)
        status = self._status_for_recording(self.selected_recording) if has_selected else "none"
        can_modify = has_selected and status not in ("recording", "processing")
        self.ctx_rename_item.setEnabled_(can_modify)
        self.ctx_archive_item.setEnabled_(can_modify)
        self.ctx_delete_item.setEnabled_(can_modify)

    def windowDidResize_(self, _):
        self._layout_root_views()
        try:
            self.refresh_detail_view()
        except Exception:
            pass

    def windowWillClose_(self, _):
        rumps.quit_application()

    @objc.python_method
    def show_window(self):
        self.window.makeKeyAndOrderFront_(None)
        app = NSApp()
        if app:
            app.activateIgnoringOtherApps_(True)
