import objc
import rumps
from AppKit import (
    NSApp,
    NSAppearance,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSImage,
    NSImageOnly,
    NSMenu,
    NSMenuItem,
    NSProgressIndicator,
    NSPopUpButton,
    NSScrollView,
    NSTableColumn,
    NSTableCellView,
    NSTableRowView,
    NSTableView,
    NSTextField,
    NSTextView,
    NSTrackingArea,
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
    NSTrackingActiveInActiveApp,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSEventModifierFlagCommand,
)

from steno_app.i18n import tr
from steno_app.ui.design_tokens import font_body, font_heading, ui_color

try:
    from WebKit import WKWebView
    HAS_WEBKIT = True
except Exception:
    WKWebView = None
    HAS_WEBKIT = False


class PromptTextView(NSTextView):
    def keyDown_(self, event):
        # Explicitly support core Cmd shortcuts in the prompt textarea.
        try:
            modifiers = int(event.modifierFlags())
            if modifiers & int(NSEventModifierFlagCommand):
                key_code = int(event.keyCode())
                # Physical key codes on macOS keyboards:
                # A=0, X=7, C=8. Works regardless of current input locale/layout.
                if key_code == 0:
                    self.selectAll_(None)
                    return
                if key_code == 8:
                    self.copy_(None)
                    return
                if key_code == 7:
                    self.cut_(None)
                    return
                if key_code == 9:
                    self.paste_(None)
                    return
        except Exception:
            pass
        objc.super(PromptTextView, self).keyDown_(event)


class SidebarRecordingRowView(NSTableRowView):
    def initWithFrame_(self, frame):
        self = objc.super(SidebarRecordingRowView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._hovered = False
        self._tracking_area = None
        return self

    def updateTrackingAreas(self):
        if self._tracking_area is not None:
            self.removeTrackingArea_(self._tracking_area)
            self._tracking_area = None
        options = NSTrackingMouseEnteredAndExited | NSTrackingInVisibleRect | NSTrackingActiveInActiveApp
        self._tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            ((0.0, 0.0), (0.0, 0.0)),
            options,
            self,
            None,
        )
        self.addTrackingArea_(self._tracking_area)
        objc.super(SidebarRecordingRowView, self).updateTrackingAreas()

    def mouseEntered_(self, _):
        self._hovered = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, _):
        self._hovered = False
        self.setNeedsDisplay_(True)

    def drawBackgroundInRect_(self, _):
        # Soft hover state for non-selected rows.
        if self._hovered and not self.isSelected():
            bounds = self.bounds()
            inset_x = 0.0
            inset_y = 1.0
            width = max(0.0, bounds[1][0] - (inset_x * 2.0))
            height = max(0.0, bounds[1][1] - (inset_y * 2.0))
            hover_rect = ((inset_x, inset_y), (width, height))
            fill = ui_color("highlight", alpha=0.45)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(hover_rect, 10.0, 10.0)
            fill.setFill()
            path.fill()

    def drawSelectionInRect_(self, _):
        bounds = self.bounds()
        inset_x = 0.0
        inset_y = 1.0
        width = max(0.0, bounds[1][0] - (inset_x * 2.0))
        height = max(0.0, bounds[1][1] - (inset_y * 2.0))
        selection_rect = ((inset_x, inset_y), (width, height))

        # Matte neutral (non-blue) selection.
        fill = ui_color("accent_dark", alpha=0.9)
        stroke = ui_color("border", alpha=1.0)

        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(selection_rect, 10.0, 10.0)
        fill.setFill()
        path.fill()
        stroke.setStroke()
        path.setLineWidth_(1.0)
        path.stroke()


class SidebarRecordingCellView(NSTableCellView):
    def initWithFrame_(self, frame):
        self = objc.super(SidebarRecordingCellView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setWantsLayer_(False)
        self.text_label = NSTextField.alloc().initWithFrame_(((14.0, 0.0), (220.0, 22.0)))
        self.text_label.setBezeled_(False)
        self.text_label.setDrawsBackground_(False)
        self.text_label.setEditable_(False)
        self.text_label.setSelectable_(False)
        self.text_label.setFont_(font_body(14.0))
        self.text_label.setTextColor_(ui_color("text_dark"))
        self.text_label.setLineBreakMode_(4)
        self.text_label.setAutoresizingMask_(NSViewWidthSizable)
        self.addSubview_(self.text_label)
        self.setTextField_(self.text_label)
        self._layout_label()
        return self

    @objc.python_method
    def _layout_label(self):
        bounds = self.bounds()
        row_h = float(bounds[1][1])
        text_h = 22.0
        text_y = max(0.0, (row_h - text_h) / 2.0 - 2.0)
        text_w = max(80.0, float(bounds[1][0]) - 28.0)
        self.text_label.setFrame_(((14.0, text_y), (text_w, text_h)))

    def layout(self):
        objc.super(SidebarRecordingCellView, self).layout()
        self._layout_label()

    def setTitle_(self, title):
        self.text_label.setStringValue_(title or "")


class ModernSidebarButton(NSButton):
    def initWithFrame_(self, frame):
        self = objc.super(ModernSidebarButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self._hovered = False
        self._pressed = False
        self._tracking_area = None
        self._style_mode = "primary"
        self.setBordered_(False)
        self.setFocusRingType_(0)
        self.setFont_(font_body(16.0, strong=True))
        self.setWantsLayer_(True)
        self._apply_style()
        return self

    @objc.python_method
    def set_style_mode(self, mode):
        self._style_mode = mode or "primary"
        self._apply_style()

    @objc.python_method
    def _apply_style(self):
        if not self.layer():
            return
        if self._style_mode == "ghost":
            bg_alpha = 0.0
            border_alpha = 0.0
            radius = 8.0
            text_alpha = 1.0
            font_size = 14.0
        elif self._style_mode == "icon":
            if self._pressed:
                bg_alpha = 0.15
                border_alpha = 0.20
            elif self._hovered:
                bg_alpha = 0.11
                border_alpha = 0.17
            else:
                bg_alpha = 0.08
                border_alpha = 0.14
            radius = 12.0
            text_alpha = 1.0
            font_size = 16.0
        else:
            if self._style_mode == "primary":
                if self._pressed:
                    bg_alpha = 0.20
                    border_alpha = 0.26
                elif self._hovered:
                    bg_alpha = 0.16
                    border_alpha = 0.22
                else:
                    bg_alpha = 0.13
                    border_alpha = 0.20
                text_alpha = 1.0
                font_size = 16.0
            else:
                if self._pressed:
                    bg_alpha = 0.10
                    border_alpha = 0.16
                elif self._hovered:
                    bg_alpha = 0.075
                    border_alpha = 0.14
                else:
                    bg_alpha = 0.05
                    border_alpha = 0.10
                text_alpha = 0.98
                font_size = 16.0
            radius = 10.0
        self.setFont_(font_body(font_size, strong=True))
        self.setContentTintColor_(ui_color("text_dark", alpha=text_alpha))
        self.layer().setCornerRadius_(radius)
        self.layer().setBorderWidth_(1.0 if border_alpha > 0 else 0.0)
        if self._style_mode == "primary":
            self.layer().setBackgroundColor_(ui_color("brand_blue", alpha=max(0.85, bg_alpha)).CGColor())
            self.layer().setBorderColor_(ui_color("brand_blue", alpha=max(0.9, border_alpha)).CGColor())
            self.setContentTintColor_(ui_color("bg_primary"))
        elif self._style_mode == "icon":
            self.layer().setBackgroundColor_(ui_color("accent_light", alpha=max(0.8, bg_alpha)).CGColor())
            self.layer().setBorderColor_(ui_color("border", alpha=max(0.8, border_alpha)).CGColor())
        else:
            self.layer().setBackgroundColor_(ui_color("accent_light", alpha=max(0.75, bg_alpha)).CGColor())
            self.layer().setBorderColor_(ui_color("border", alpha=max(0.75, border_alpha)).CGColor())

    def updateTrackingAreas(self):
        if self._tracking_area is not None:
            self.removeTrackingArea_(self._tracking_area)
            self._tracking_area = None
        options = NSTrackingMouseEnteredAndExited | NSTrackingInVisibleRect | NSTrackingActiveInActiveApp
        self._tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            ((0.0, 0.0), (0.0, 0.0)),
            options,
            self,
            None,
        )
        self.addTrackingArea_(self._tracking_area)
        objc.super(ModernSidebarButton, self).updateTrackingAreas()

    def mouseEntered_(self, _):
        self._hovered = True
        self._apply_style()

    def mouseExited_(self, _):
        self._hovered = False
        self._pressed = False
        self._apply_style()

    def mouseDown_(self, event):
        self._pressed = True
        self._apply_style()
        try:
            objc.super(ModernSidebarButton, self).mouseDown_(event)
        finally:
            self._pressed = False
            self._apply_style()


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
            label.setFont_(font_heading(14.0))
        elif secondary:
            label.setFont_(font_body(14.0))
            label.setTextColor_(ui_color("text_dark", alpha=0.72))
        else:
            label.setFont_(font_body(16.0))
            label.setTextColor_(ui_color("text_dark"))
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
    def _sidebar_button(self, frame, title, action, mode="primary"):
        button = ModernSidebarButton.alloc().initWithFrame_(frame)
        button.setTitle_(title)
        button.setTarget_(self)
        button.setAction_(action)
        button.set_style_mode(mode)
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
        try:
            self.window.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameAqua"))
        except Exception:
            pass

        root = self.window.contentView()
        self.sidebar_width = 300.0
        self.sidebar_pad_x = 20.0
        self.sidebar_inner_width = self.sidebar_width - (self.sidebar_pad_x * 2.0)
        self.sidebar_view = NSView.alloc().initWithFrame_(((0.0, 0.0), (self.sidebar_width, root.bounds()[1][1])))
        self.sidebar_view.setAutoresizingMask_(NSViewHeightSizable | NSViewMaxXMargin)
        self.sidebar_view.setWantsLayer_(True)
        self.sidebar_view.layer().setBackgroundColor_(ui_color("bg_secondary").CGColor())
        root.addSubview_(self.sidebar_view)

        self.content_view = NSView.alloc().initWithFrame_(((self.sidebar_width, 0.0), (root.bounds()[1][0] - self.sidebar_width, root.bounds()[1][1])))
        self.content_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.content_view.setWantsLayer_(True)
        self.content_view.layer().setBackgroundColor_(ui_color("bg_primary").CGColor())
        root.addSubview_(self.content_view)

        self.sidebar_seam_view = NSView.alloc().initWithFrame_(((self.sidebar_width - 4.0, 0.0), (8.0, root.bounds()[1][1])))
        self.sidebar_seam_view.setAutoresizingMask_(NSViewHeightSizable | NSViewMinXMargin)
        self.sidebar_seam_view.setWantsLayer_(True)
        self.sidebar_seam_view.layer().setBackgroundColor_(ui_color("divider").CGColor())
        root.addSubview_(self.sidebar_seam_view)

        self.start_stop_button = self._sidebar_button(
            ((self.sidebar_pad_x, self.sidebar_view.bounds()[1][1] - 46.0), (self.sidebar_inner_width, 32.0)),
            tr("main.start_recording"),
            "onStartStop:",
        )
        self.start_stop_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
        self.sidebar_view.addSubview_(self.start_stop_button)

        self.import_button = self._sidebar_button(
            ((self.sidebar_pad_x, self.sidebar_view.bounds()[1][1] - 84.0), (self.sidebar_inner_width, 28.0)),
            tr("main.import_meeting"),
            "onImportMeeting:",
            mode="secondary",
        )
        self.import_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
        self.sidebar_view.addSubview_(self.import_button)

        list_top = self.sidebar_view.bounds()[1][1] - 112.0
        list_bottom = 88.0
        self.recordings_scroll = NSScrollView.alloc().initWithFrame_(
            ((self.sidebar_pad_x, list_bottom), (self.sidebar_inner_width, max(100.0, list_top - list_bottom)))
        )
        self.recordings_scroll.setHasVerticalScroller_(True)
        self.recordings_scroll.setHasHorizontalScroller_(False)
        self.recordings_scroll.setBorderType_(0)
        self.recordings_scroll.setDrawsBackground_(False)
        self.recordings_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        self.recordings_table = NSTableView.alloc().initWithFrame_(
            ((0.0, 0.0), (self.sidebar_inner_width, max(100.0, list_top - list_bottom)))
        )
        self.recordings_table.setDelegate_(self)
        self.recordings_table.setDataSource_(self)
        self.recordings_table.setTarget_(self)
        self.recordings_table.setDoubleAction_("onRecordingsDoubleClick:")
        self.recordings_table.setHeaderView_(None)
        self.recordings_table.setUsesAlternatingRowBackgroundColors_(False)
        # Keep regular selection mode so row-view selection drawing is always invoked.
        self.recordings_table.setSelectionHighlightStyle_(0)
        self.recordings_table.setBackgroundColor_(NSColor.clearColor())
        self.recordings_table.setIntercellSpacing_((0.0, 6.0))
        self.recordings_table.setRowHeight_(34.0)
        self.recordings_table.setFocusRingType_(1)
        column = NSTableColumn.alloc().initWithIdentifier_("recording")
        column.setWidth_(self.sidebar_inner_width - 4.0)
        try:
            column.setEditable_(True)
        except Exception:
            pass
        self.recordings_table.addTableColumn_(column)
        self.recordings_scroll.setDocumentView_(self.recordings_table)
        self.sidebar_view.addSubview_(self.recordings_scroll)
        self._build_recordings_context_menu()

        self.settings_button = self._sidebar_button(
            ((self.sidebar_pad_x, 30.0), (40.0, 40.0)),
            "",
            "onOpenSettings:",
            mode="icon",
        )
        self.settings_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMaxYMargin)
        try:
            settings_icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "slider.horizontal.3",
                None,
            )
        except Exception:
            settings_icon = None
        if settings_icon is not None:
            try:
                settings_icon.setTemplate_(True)
            except Exception:
                pass
            self.settings_button.setImage_(settings_icon)
            self.settings_button.setImagePosition_(NSImageOnly)
        else:
            self.settings_button.setTitle_("≡")
            self.settings_button.setFont_(font_heading(21.0))
        self.sidebar_view.addSubview_(self.settings_button)

        self.detail_title_label = self._label(
            ((24.0, self.content_view.bounds()[1][1] - 52.0), (760.0, 28.0)),
            tr("main.select_recording"),
            bold=True,
        )
        self.detail_title_label.setFont_(font_heading(28.0))
        self.detail_title_label.setTextColor_(ui_color("text_dark"))
        self.detail_title_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        self.content_view.addSubview_(self.detail_title_label)

        self.files_label = self._label(
            ((24.0, self.content_view.bounds()[1][1] - 118.0), (820.0, 54.0)),
            tr("main.files_default"),
            secondary=True,
        )
        self.files_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        self.content_view.addSubview_(self.files_label)

        self.prompt_template_label = self._label(
            ((24.0, self.content_view.bounds()[1][1] - 152.0), (260.0, 20.0)),
            tr("main.prompt_template"),
            bold=True,
        )
        self.prompt_template_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        self.content_view.addSubview_(self.prompt_template_label)

        self.prompt_template_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            ((24.0, self.content_view.bounds()[1][1] - 184.0), (380.0, 28.0)),
            False,
        )
        self.prompt_template_popup.setTarget_(self)
        self.prompt_template_popup.setAction_("onPromptTemplateChanged:")
        self.prompt_template_popup.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
        self.content_view.addSubview_(self.prompt_template_popup)

        self.process_button = self._sidebar_button(
            ((24.0, self.content_view.bounds()[1][1] - 160.0), (120.0, 30.0)),
            tr("main.process"),
            "onProcessSelected:",
            mode="secondary",
        )
        self.process_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
        self.content_view.addSubview_(self.process_button)

        self.copy_protocol_button = self._sidebar_button(
            ((156.0, self.content_view.bounds()[1][1] - 160.0), (140.0, 30.0)),
            tr("main.copy"),
            "onCopyProtocol:",
            mode="secondary",
        )
        self.copy_protocol_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
        self.content_view.addSubview_(self.copy_protocol_button)

        self.delete_protocol_button = self._sidebar_button(
            ((308.0, self.content_view.bounds()[1][1] - 160.0), (220.0, 30.0)),
            tr("main.delete_processing_result"),
            "onDeleteProcessingResult:",
            mode="secondary",
        )
        self.delete_protocol_button.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin)
        self.content_view.addSubview_(self.delete_protocol_button)

        self.loader = NSProgressIndicator.alloc().initWithFrame_(((540.0, self.content_view.bounds()[1][1] - 160.0), (24.0, 24.0)))
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
            self.prompt_scroll.layer().setBorderColor_(ui_color("border").CGColor())
        except Exception:
            pass
        self.prompt_text = PromptTextView.alloc().initWithFrame_(self.prompt_scroll.bounds())
        self.prompt_text.setEditable_(True)
        self.prompt_text.setSelectable_(True)
        self.prompt_text.setRichText_(False)
        self.prompt_text.setFont_(font_body(14.0))
        self.prompt_text.setDrawsBackground_(True)
        self.prompt_text.setBackgroundColor_(ui_color("bg_primary"))
        self.prompt_text.setTextColor_(ui_color("text_dark"))
        self.prompt_text.setInsertionPointColor_(ui_color("text_dark"))
        self.prompt_scroll.setDocumentView_(self.prompt_text)
        self.content_view.addSubview_(self.prompt_scroll)

        self.prompt_hint_label = self._label(
            ((24.0, self.content_view.bounds()[1][1] - 356.0), (700.0, 18.0)),
            tr("main.prompt_hint"),
            secondary=True,
        )
        self.prompt_hint_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        self.content_view.addSubview_(self.prompt_hint_label)

        self.user_prompt_label = self._label(
            ((24.0, self.content_view.bounds()[1][1] - 388.0), (260.0, 24.0)),
            tr("main.user_prompt_editable"),
            bold=True,
        )
        self.user_prompt_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        self.content_view.addSubview_(self.user_prompt_label)

        self.user_prompt_scroll = NSScrollView.alloc().initWithFrame_(
            ((24.0, self.content_view.bounds()[1][1] - 496.0), (self.content_view.bounds()[1][0] - 48.0, 92.0))
        )
        self.user_prompt_scroll.setHasVerticalScroller_(True)
        self.user_prompt_scroll.setHasHorizontalScroller_(False)
        self.user_prompt_scroll.setBorderType_(2)
        self.user_prompt_scroll.setDrawsBackground_(True)
        self.user_prompt_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        try:
            self.user_prompt_scroll.setWantsLayer_(True)
            self.user_prompt_scroll.layer().setCornerRadius_(6.0)
            self.user_prompt_scroll.layer().setBorderWidth_(1.0)
            self.user_prompt_scroll.layer().setBorderColor_(ui_color("border").CGColor())
        except Exception:
            pass
        self.user_prompt_text = PromptTextView.alloc().initWithFrame_(self.user_prompt_scroll.bounds())
        self.user_prompt_text.setEditable_(True)
        self.user_prompt_text.setSelectable_(True)
        self.user_prompt_text.setRichText_(False)
        self.user_prompt_text.setFont_(font_body(14.0))
        self.user_prompt_text.setDrawsBackground_(True)
        self.user_prompt_text.setBackgroundColor_(ui_color("bg_primary"))
        self.user_prompt_text.setTextColor_(ui_color("text_dark"))
        self.user_prompt_text.setInsertionPointColor_(ui_color("text_dark"))
        self.user_prompt_scroll.setDocumentView_(self.user_prompt_text)
        self.content_view.addSubview_(self.user_prompt_scroll)

        self.user_prompt_hint_label = self._label(
            ((24.0, self.content_view.bounds()[1][1] - 520.0), (700.0, 18.0)),
            tr("main.user_prompt_hint"),
            secondary=True,
        )
        self.user_prompt_hint_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        self.content_view.addSubview_(self.user_prompt_hint_label)

        protocol_frame = ((24.0, 24.0), (self.content_view.bounds()[1][0] - 48.0, self.content_view.bounds()[1][1] - 560.0))
        if HAS_WEBKIT:
            self.protocol_web_view = WKWebView.alloc().initWithFrame_(protocol_frame)
            self.protocol_web_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            self.protocol_scroll = self.protocol_web_view
            self.protocol_text = None
            self.content_view.addSubview_(self.protocol_web_view)
        else:
            self.protocol_web_view = None
            self.protocol_scroll = NSScrollView.alloc().initWithFrame_(protocol_frame)
            self.protocol_scroll.setHasVerticalScroller_(True)
            self.protocol_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            self.protocol_text = NSTextView.alloc().initWithFrame_(self.protocol_scroll.bounds())
            self.protocol_text.setEditable_(False)
            self.protocol_text.setSelectable_(True)
            self.protocol_text.setRichText_(True)
            self.protocol_text.setFont_(font_body(16.0))
            self.protocol_text.setDrawsBackground_(True)
            self.protocol_text.setTextColor_(ui_color("text_dark"))
            self.protocol_text.setBackgroundColor_(ui_color("bg_primary"))
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
        self.sidebar_seam_view.setFrame_(((self.sidebar_width - 4.0, 0.0), (8.0, root_height)))

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

        self.ctx_delete_processing_result_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(tr("main.ctx_delete_processing_result"), "onContextDeleteProcessingResult:", "")
        self.ctx_delete_processing_result_item.setTarget_(self)
        self.recordings_context_menu.addItem_(self.ctx_delete_processing_result_item)

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
        can_delete_processing_result = has_selected and status == "processed"
        self.ctx_rename_item.setEnabled_(can_modify)
        self.ctx_archive_item.setEnabled_(can_modify)
        self.ctx_delete_processing_result_item.setEnabled_(can_delete_processing_result)
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
