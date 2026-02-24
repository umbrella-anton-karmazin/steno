import os
import re
from html import escape

import objc
import rumps
from AppKit import NSColor, NSFont, NSFontAttributeName
from Foundation import NSIndexSet, NSMutableAttributedString, NSURL

try:
    from AVFoundation import AVURLAsset
    from CoreMedia import CMTimeGetSeconds
except Exception:
    AVURLAsset = None
    CMTimeGetSeconds = None

from steno_app.i18n import tr
from steno_app.config import (
    ConfigManager,
    get_prompt_template_by_id,
    get_prompt_templates,
    get_selected_prompt_template,
    set_selected_prompt_template,
)
from steno_app.ui.main_window_view import SidebarRecordingCellView, SidebarRecordingRowView


class MainWindowStateMixin:
    @objc.python_method
    def _apply_inline_bold_html(self, text):
        raw = str(text or "")
        parts = re.split(r"(\*\*.*?\*\*)", raw)
        out = []
        for part in parts:
            if part.startswith("**") and part.endswith("**") and len(part) >= 4:
                out.append(f"<strong>{escape(part[2:-2])}</strong>")
            else:
                out.append(escape(part))
        return "".join(out)

    @objc.python_method
    def _markdown_to_html(self, text):
        lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        html = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                html.append("<div class='spacer'></div>")
                i += 1
                continue

            # Tables
            if self._is_table_line(line):
                block = []
                j = i
                while j < len(lines) and self._is_table_line(lines[j]):
                    block.append(lines[j])
                    j += 1
                rows = [self._split_table_row(x) for x in block]
                rows = [r for r in rows if r]
                if rows:
                    html.append("<table><tbody>")
                    header_done = False
                    for row in rows:
                        if self._is_table_separator_row(row):
                            header_done = True
                            continue
                        tag = "th" if not header_done else "td"
                        html.append("<tr>")
                        for cell in row:
                            html.append(f"<{tag}>{self._apply_inline_bold_html(cell)}</{tag}>")
                        html.append("</tr>")
                    html.append("</tbody></table>")
                i = j
                continue

            # Headings
            if stripped.startswith("### "):
                html.append(f"<h3>{self._apply_inline_bold_html(stripped[4:])}</h3>")
                i += 1
                continue
            if stripped.startswith("## "):
                html.append(f"<h2>{self._apply_inline_bold_html(stripped[3:])}</h2>")
                i += 1
                continue
            if stripped.startswith("# "):
                html.append(f"<h1>{self._apply_inline_bold_html(stripped[2:])}</h1>")
                i += 1
                continue

            # Bullet list
            if stripped.startswith("* "):
                html.append("<ul>")
                while i < len(lines) and lines[i].strip().startswith("* "):
                    li = lines[i].strip()[2:]
                    html.append(f"<li>{self._apply_inline_bold_html(li)}</li>")
                    i += 1
                html.append("</ul>")
                continue

            # Paragraph (preserve manual line breaks until blank/special block)
            para = [line]
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                s = nxt.strip()
                if not s:
                    break
                if s.startswith("#") or s.startswith("* ") or self._is_table_line(nxt):
                    break
                para.append(nxt)
                j += 1
            html.append("<p>" + "<br/>".join(self._apply_inline_bold_html(x) for x in para) + "</p>")
            i = j

        body = "\n".join(html)
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    :root {{ color-scheme: light dark; }}
    :root {{
      --fg-light: #1f2328;
      --fg-dark: #e7ebf2;
      --border-light: rgba(80, 88, 102, 0.28);
      --border-dark: rgba(171, 185, 207, 0.34);
      --th-light: rgba(127,127,127,0.12);
      --th-dark: rgba(157, 171, 196, 0.18);
    }}
    html, body {{
      margin: 0; padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 16px;
      line-height: 1.45;
      background: transparent;
      color: var(--fg-light);
    }}
    @media (prefers-color-scheme: dark) {{
      html, body {{ color: var(--fg-dark); }}
    }}
    .wrap {{ padding: 4px 4px 8px 4px; }}
    h1 {{ font-size: 1.40em; margin: 0.7em 0 0.25em; }}
    h2 {{ font-size: 1.20em; margin: 0.7em 0 0.25em; }}
    h3 {{ font-size: 1.08em; margin: 0.65em 0 0.22em; }}
    p {{ margin: 0.35em 0; }}
    ul {{ margin: 0.25em 0 0.55em 1.25em; padding: 0; }}
    li {{ margin: 0.2em 0; }}
    .spacer {{ height: 0.55em; }}
    table {{
      border-collapse: collapse;
      margin: 0.45em 0 0.65em;
      width: 100%;
      font-size: 0.95em;
    }}
    th, td {{
      border: 1px solid var(--border-light);
      padding: 6px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: var(--th-light); font-weight: 600; }}
    @media (prefers-color-scheme: dark) {{
      th, td {{ border-color: var(--border-dark); }}
      th {{ background: var(--th-dark); }}
    }}
  </style>
</head>
<body><div class="wrap">{body}</div></body>
</html>"""

    @objc.python_method
    def _plain_to_html(self, text):
        value = escape(str(text or ""))
        return f"""<!doctype html>
<html><head><meta charset="utf-8" />
<style>
  :root {{ color-scheme: light dark; }}
  :root {{
    --fg-light: #1f2328;
    --fg-dark: #e7ebf2;
  }}
  html, body {{
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 12px;
    line-height: 1.45;
    background: transparent;
    color: var(--fg-light);
  }}
  @media (prefers-color-scheme: dark) {{
    html, body {{ color: var(--fg-dark); }}
  }}
  .wrap {{ white-space: pre-wrap; padding: 4px; }}
</style>
</head><body><div class="wrap">{value}</div></body></html>"""

    @objc.python_method
    def _is_table_line(self, line):
        stripped = (line or "").strip()
        return stripped.count("|") >= 2

    @objc.python_method
    def _split_table_row(self, line):
        row = str(line or "").strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [c.strip() for c in row.split("|")]

    @objc.python_method
    def _is_table_separator_row(self, cells):
        if not cells:
            return False
        for c in cells:
            cleaned = c.replace("-", "").replace(":", "").replace(" ", "")
            if cleaned:
                return False
        return True

    @objc.python_method
    def _format_markdown_table_block(self, lines):
        rows = [self._split_table_row(line) for line in lines]
        rows = [r for r in rows if r]
        if not rows:
            return lines

        widths = []
        for row in rows:
            if len(row) > len(widths):
                widths.extend([0] * (len(row) - len(widths)))
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))

        out = []
        for row in rows:
            if self._is_table_separator_row(row):
                sep = ["-" * max(3, widths[i]) for i in range(len(widths))]
                out.append("| " + " | ".join(sep) + " |")
                continue
            padded = []
            for i in range(len(widths)):
                value = row[i] if i < len(row) else ""
                padded.append(value.ljust(widths[i]))
            out.append("| " + " | ".join(padded) + " |")
        return out

    @objc.python_method
    def _apply_inline_bold(self, line):
        text = str(line or "")
        spans = []
        out = []
        i = 0
        out_len = 0
        while i < len(text):
            if text.startswith("**", i):
                end = text.find("**", i + 2)
                if end != -1:
                    chunk = text[i + 2 : end]
                    start = out_len
                    out.append(chunk)
                    out_len += len(chunk)
                    spans.append((start, len(chunk)))
                    i = end + 2
                    continue
            out.append(text[i])
            out_len += 1
            i += 1
        return "".join(out), spans

    @objc.python_method
    def _build_markdown_attributed(self, text):
        source = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = source.split("\n")

        # Pre-format markdown table blocks for monospaced rendering.
        normalized_lines = []
        i = 0
        while i < len(lines):
            if self._is_table_line(lines[i]):
                j = i
                block = []
                while j < len(lines) and self._is_table_line(lines[j]):
                    block.append(lines[j])
                    j += 1
                normalized_lines.extend(self._format_markdown_table_block(block))
                i = j
                continue
            normalized_lines.append(lines[i])
            i += 1

        # Build plain text + style ranges.
        output_lines = []
        heading_ranges = []
        bold_ranges = []
        table_ranges = []
        cursor = 0
        for line in normalized_lines:
            original = line
            heading_level = 0
            stripped = line.lstrip()
            leading = len(line) - len(stripped)
            if stripped.startswith("### "):
                heading_level = 3
                line = (" " * leading) + stripped[4:]
            elif stripped.startswith("## "):
                heading_level = 2
                line = (" " * leading) + stripped[3:]
            elif stripped.startswith("# "):
                heading_level = 1
                line = (" " * leading) + stripped[2:]

            is_table = self._is_table_line(original)
            clean, inline_spans = self._apply_inline_bold(line if not is_table else original)
            output_lines.append(clean)
            line_len = len(clean)

            if heading_level > 0 and line_len > 0:
                heading_ranges.append((cursor, line_len, heading_level))
            if is_table and line_len > 0:
                table_ranges.append((cursor, line_len))
            for start, length in inline_spans:
                if length > 0:
                    bold_ranges.append((cursor + start, length))

            cursor += line_len + 1  # include trailing newline after each line

        final_text = "\n".join(output_lines)
        attr = NSMutableAttributedString.alloc().initWithString_(final_text)

        base_font = NSFont.systemFontOfSize_(13.0)
        bold_font = NSFont.boldSystemFontOfSize_(13.0)
        h1_font = NSFont.boldSystemFontOfSize_(24.0)
        h2_font = NSFont.boldSystemFontOfSize_(20.0)
        h3_font = NSFont.boldSystemFontOfSize_(16.0)
        mono_font = NSFont.userFixedPitchFontOfSize_(12.5) or NSFont.systemFontOfSize_(12.5)

        full_len = len(final_text)
        if full_len > 0:
            attr.addAttribute_value_range_(NSFontAttributeName, base_font, (0, full_len))

        for start, length in bold_ranges:
            attr.addAttribute_value_range_(NSFontAttributeName, bold_font, (start, length))
        for start, length in table_ranges:
            attr.addAttribute_value_range_(NSFontAttributeName, mono_font, (start, length))
        for start, length, level in heading_ranges:
            font = h1_font if level == 1 else h2_font if level == 2 else h3_font
            attr.addAttribute_value_range_(NSFontAttributeName, font, (start, length))

        return attr

    @objc.python_method
    def _set_protocol_text(self, text, parse_markdown=True):
        value = str(text or "")
        web_view = getattr(self, "protocol_web_view", None)
        if web_view is not None:
            try:
                html = self._markdown_to_html(value) if parse_markdown else self._plain_to_html(value)
                web_view.loadHTMLString_baseURL_(html, None)
                return
            except Exception:
                pass
        if parse_markdown and value:
            try:
                attributed = self._build_markdown_attributed(value)
                self.protocol_text.textStorage().setAttributedString_(attributed)
                return
            except Exception:
                pass
        self.protocol_text.setString_(value)

    @objc.python_method
    def _format_duration_for_ui(self, total_seconds):
        if total_seconds is None:
            return ""
        total_seconds = max(0, int(total_seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        # Rule:
        # - if hours exist: show HHч. MMм. (omit seconds)
        # - otherwise: show MMм. SS с. (omit hours)
        if hours > 0:
            return f"{hours:02d}ч. {minutes:02d}м."
        if minutes > 0:
            return f"{minutes:02d}м. {seconds:02d} с."
        return f"{seconds:02d} с."

    @objc.python_method
    def _video_duration_seconds(self, filename):
        if not filename:
            return None
        if AVURLAsset is None or CMTimeGetSeconds is None:
            return None

        video_path = os.path.join(self.app.config["save_dir"], filename)
        if not os.path.exists(video_path):
            return None

        try:
            mtime = os.path.getmtime(video_path)
        except Exception:
            mtime = None

        cache = getattr(self, "video_duration_cache", None)
        if isinstance(cache, dict):
            cached = cache.get(filename)
            if cached and cached[0] == mtime:
                return cached[1]
        else:
            self.video_duration_cache = {}
            cache = self.video_duration_cache

        duration_seconds = None
        try:
            asset = AVURLAsset.URLAssetWithURL_options_(NSURL.fileURLWithPath_(video_path), None)
            seconds = CMTimeGetSeconds(asset.duration())
            if seconds == seconds and seconds >= 0:  # NaN-safe check
                duration_seconds = int(round(float(seconds)))
        except Exception:
            duration_seconds = None

        cache[filename] = (mtime, duration_seconds)
        return duration_seconds

    @objc.python_method
    def _estimate_text_height(self, text_view, minimum, maximum):
        try:
            text_view.layoutManager().glyphRangeForTextContainer_(text_view.textContainer())
            used = text_view.layoutManager().usedRectForTextContainer_(text_view.textContainer())
            estimated = float(used.size.height) + 18.0
            return max(minimum, min(maximum, estimated))
        except Exception:
            try:
                text = str(text_view.string() or "")
                lines = max(1, len(text.splitlines()))
                estimated = 18.0 + lines * 18.0
                return max(minimum, min(maximum, estimated))
            except Exception:
                return minimum

    @objc.python_method
    def _estimate_prompt_height(self):
        return self._estimate_text_height(self.prompt_text, minimum=120.0, maximum=300.0)

    @objc.python_method
    def _estimate_user_prompt_height(self):
        return self._estimate_text_height(self.user_prompt_text, minimum=84.0, maximum=220.0)

    @objc.python_method
    def _apply_dynamic_detail_layout(self, status):
        root_w, root_h = self.content_view.bounds()[1]
        content_w = max(320.0, root_w)
        pad = 24.0
        full_w = content_w - (pad * 2.0)
        bottom_pad = 24.0

        title_h = 28.0
        files_h = 76.0
        controls_h = 30.0
        template_label_h = 20.0
        template_popup_h = 28.0
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
            # tighter gap between files and form controls
            cursor_top -= 8.0

            template_label_y = cursor_top - template_label_h
            self.prompt_template_label.setFrame_(((pad, template_label_y), (320.0, template_label_h)))
            cursor_top = template_label_y - 6.0

            template_popup_y = cursor_top - template_popup_h
            self.prompt_template_popup.setFrame_(((pad, template_popup_y), (380.0, template_popup_h)))
            cursor_top = template_popup_y - 10.0

            prompt_label_y = cursor_top - prompt_label_h
            self.prompt_label.setFrame_(((pad, prompt_label_y), (260.0, prompt_label_h)))
            cursor_top = prompt_label_y - 6.0

            prompt_h = self._estimate_prompt_height()
            prompt_y = cursor_top - prompt_h
            self.prompt_scroll.setFrame_(((pad, prompt_y), (full_w, prompt_h)))
            cursor_top = prompt_y - 4.0

            hint_y = cursor_top - hint_h
            self.prompt_hint_label.setFrame_(((pad, hint_y), (full_w, hint_h)))
            cursor_top = hint_y - 10.0

            user_prompt_label_y = cursor_top - prompt_label_h
            self.user_prompt_label.setFrame_(((pad, user_prompt_label_y), (260.0, prompt_label_h)))
            cursor_top = user_prompt_label_y - 6.0

            user_prompt_h = self._estimate_user_prompt_height()
            user_prompt_y = cursor_top - user_prompt_h
            self.user_prompt_scroll.setFrame_(((pad, user_prompt_y), (full_w, user_prompt_h)))
            cursor_top = user_prompt_y - 4.0

            user_hint_y = cursor_top - hint_h
            self.user_prompt_hint_label.setFrame_(((pad, user_hint_y), (full_w, hint_h)))
            cursor_top = user_hint_y - 8.0

            # \"No protocol yet\" message area
            protocol_y = cursor_top - info_h
            self.protocol_scroll.setFrame_(((pad, protocol_y), (full_w, info_h)))
            cursor_top = protocol_y - 8.0

            # Process button below \"No protocol yet\" text
            controls_y = max(bottom_pad, cursor_top - controls_h)
            self.process_button.setFrame_(((pad, controls_y), (140.0, controls_h)))
            self.loader.setFrame_(((pad + 150.0, controls_y + 3.0), (24.0, 24.0)))
            self.copy_protocol_button.setFrame_(((pad, controls_y), (140.0, controls_h)))
            self.delete_protocol_button.setFrame_(((pad + 148.0, controls_y), (220.0, controls_h)))
        else:
            self.prompt_template_popup.setFrame_(((pad, root_h + 200.0), (380.0, template_popup_h)))
            # tighter gap between files and controls
            controls_y = cursor_top - 8.0 - controls_h
            self.process_button.setFrame_(((pad, controls_y), (120.0, controls_h)))
            self.copy_protocol_button.setFrame_(((pad, controls_y), (140.0, controls_h)))
            self.delete_protocol_button.setFrame_(((pad + 148.0, controls_y), (220.0, controls_h)))
            self.loader.setFrame_(((pad + 376.0, controls_y + 3.0), (24.0, 24.0)))

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
    def _current_user_prompt_text(self):
        try:
            return str(self.user_prompt_text.string())
        except Exception:
            selected = get_selected_prompt_template(self.app.config) or {}
            return str(selected.get("user_prompt") or "")

    @objc.python_method
    def _reload_prompt_templates_popup(self, selected_template_id=None):
        templates = get_prompt_templates(self.app.config, include_archived=False)
        self.prompt_template_popup.removeAllItems()
        for template in templates:
            name = self._template_display_name(template, include_builtin_marker=False)
            self.prompt_template_popup.addItemWithTitle_(name)
            try:
                item = self.prompt_template_popup.lastItem()
                if item is not None:
                    item.setRepresentedObject_(str(template.get("id") or ""))
            except Exception:
                pass
        if not templates:
            return
        target_id = str(selected_template_id or "").strip()
        if not target_id:
            current = get_selected_prompt_template(self.app.config) or {}
            target_id = str(current.get("id") or "").strip()
        selected_index = 0
        for idx, template in enumerate(templates):
            if str(template.get("id") or "") == target_id:
                selected_index = idx
                break
        self.prompt_template_popup.selectItemAtIndex_(selected_index)

    @objc.python_method
    def _selected_template_id_from_popup(self):
        try:
            item = self.prompt_template_popup.selectedItem()
            if item is None:
                return ""
            value = item.representedObject()
            return str(value or "")
        except Exception:
            return ""

    @objc.python_method
    def apply_prompt_template_for_selected(self, template_id):
        if not self.selected_recording:
            return
        if self._status_for_recording(self.selected_recording) != "unprocessed":
            return
        template = get_prompt_template_by_id(self.app.config, template_id)
        if not template or template.get("archived"):
            return

        system_text = str(template.get("system_prompt") or "")
        user_text = str(template.get("user_prompt") or "")
        self.prompt_text.setString_(system_text)
        self.user_prompt_text.setString_(user_text)
        self.prompt_drafts[self.selected_recording] = system_text
        self.user_prompt_drafts[self.selected_recording] = user_text
        self.template_id_drafts[self.selected_recording] = str(template.get("id") or "")

        if set_selected_prompt_template(self.app.config, template.get("id")):
            ConfigManager.save(self.app.config)

        self.refresh_detail_view()

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
        self.user_prompt_drafts[self.selected_recording] = self._current_user_prompt_text()
        selected_template_id = self._selected_template_id_from_popup()
        if selected_template_id:
            self.template_id_drafts[self.selected_recording] = selected_template_id

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
        return os.path.splitext(filename)[0]

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
            self.start_stop_button.setTitle_(tr("main.stop_recording"))
        elif self.app.is_waiting_permissions:
            self.start_stop_button.setTitle_(tr("main.starting"))
        elif self.app.is_processing:
            self.start_stop_button.setTitle_(tr("main.start_recording"))
        else:
            self.start_stop_button.setTitle_(tr("main.start_recording"))

        self.start_stop_button.setEnabled_(
            (not self.app.is_processing or self.app.is_recording)
            and not self.app.is_waiting_permissions
        )

        if getattr(self.app, "is_importing", False):
            progress = int(max(0, min(100, round(float(getattr(self.app, "import_progress", 0.0)) * 100))))
            self.import_button.setTitle_(tr("main.importing_progress", percent=progress))
            self.import_button.setEnabled_(False)
        else:
            self.import_button.setTitle_(tr("main.import_meeting"))
            self.import_button.setEnabled_(True)

    @objc.python_method
    def refresh_file_lists(self):
        self.recording_files = self.app.meetings_service.list_recent_recordings(limit=200)
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
            self.delete_protocol_button.setHidden_(True)
            self.prompt_template_label.setHidden_(True)
            self.prompt_template_popup.setHidden_(True)
            self.prompt_label.setHidden_(True)
            self.prompt_scroll.setHidden_(True)
            self.prompt_hint_label.setHidden_(True)
            self.user_prompt_label.setHidden_(True)
            self.user_prompt_scroll.setHidden_(True)
            self.user_prompt_hint_label.setHidden_(True)
            self.prompt_loaded_for = None
            self.loader.stopAnimation_(None)
            self._set_protocol_text(tr("main.select_recording_hint"), parse_markdown=False)
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
            template_id = self.template_id_drafts.get(video_name)
            if not template_id:
                selected_template = get_selected_prompt_template(self.app.config) or {}
                template_id = selected_template.get("id")
            template = get_prompt_template_by_id(self.app.config, template_id) or get_selected_prompt_template(self.app.config) or {}
            template_id = str(template.get("id") or "")

            prompt_value = self.prompt_drafts.get(video_name)
            if prompt_value is None:
                prompt_value = str(template.get("system_prompt") or self.app.config.get("prompt", ""))
            self.prompt_text.setString_(str(prompt_value))

            user_prompt_value = self.user_prompt_drafts.get(video_name)
            if user_prompt_value is None:
                user_prompt_value = str(template.get("user_prompt") or "")
            self.user_prompt_text.setString_(str(user_prompt_value))

            self._reload_prompt_templates_popup(template_id)
            if template_id:
                self.template_id_drafts[video_name] = template_id
            self.prompt_loaded_for = video_name

        self._apply_dynamic_detail_layout(status)

        display_name = self._display_meeting_name(video_name)
        self.detail_title_label.setStringValue_(display_name)
        audio_label = mic_name if os.path.exists(mic_path) else tr("main.audio_missing")
        files_text = tr("main.files_line", video=video_name, audio=audio_label)
        if self.app.meetings_service.is_imported_recording(video_name):
            files_text += "\n" + tr("main.source_imported")
        if status == "recording" and self._is_recording_file(video_name):
            duration_seconds = self.app.get_live_recording_elapsed_seconds()
        else:
            duration_seconds = self._video_duration_seconds(video_name)
        if duration_seconds is not None:
            files_text += "\n" + tr(
                "main.duration_line",
                duration=self._format_duration_for_ui(duration_seconds),
            )
        self.files_label.setStringValue_(files_text)

        if status == "processing":
            self.process_button.setHidden_(False)
            self.process_button.setEnabled_(False)
            self.copy_protocol_button.setHidden_(True)
            self.delete_protocol_button.setHidden_(True)
            self.prompt_template_label.setHidden_(True)
            self.prompt_template_popup.setHidden_(True)
            self.prompt_label.setHidden_(True)
            self.prompt_scroll.setHidden_(True)
            self.prompt_hint_label.setHidden_(True)
            self.user_prompt_label.setHidden_(True)
            self.user_prompt_scroll.setHidden_(True)
            self.user_prompt_hint_label.setHidden_(True)
            self.loader.startAnimation_(None)
        elif status == "unprocessed":
            self.process_button.setHidden_(False)
            self.process_button.setEnabled_(not self.app.is_processing)
            self.copy_protocol_button.setHidden_(True)
            self.delete_protocol_button.setHidden_(True)
            self.prompt_template_label.setHidden_(False)
            self.prompt_template_popup.setHidden_(False)
            self.prompt_label.setHidden_(False)
            self.prompt_scroll.setHidden_(False)
            self.prompt_hint_label.setHidden_(False)
            self.user_prompt_label.setHidden_(False)
            self.user_prompt_scroll.setHidden_(False)
            self.user_prompt_hint_label.setHidden_(False)
            self.loader.stopAnimation_(None)
        elif status == "recording":
            self.process_button.setHidden_(True)
            self.copy_protocol_button.setHidden_(True)
            self.delete_protocol_button.setHidden_(True)
            self.prompt_template_label.setHidden_(True)
            self.prompt_template_popup.setHidden_(True)
            self.prompt_label.setHidden_(True)
            self.prompt_scroll.setHidden_(True)
            self.prompt_hint_label.setHidden_(True)
            self.user_prompt_label.setHidden_(True)
            self.user_prompt_scroll.setHidden_(True)
            self.user_prompt_hint_label.setHidden_(True)
            self.loader.stopAnimation_(None)
        else:
            self.process_button.setHidden_(True)
            self.copy_protocol_button.setHidden_(False)
            self.copy_protocol_button.setEnabled_(has_protocol)
            self.delete_protocol_button.setHidden_(False)
            self.delete_protocol_button.setEnabled_(has_protocol)
            self.prompt_template_label.setHidden_(True)
            self.prompt_template_popup.setHidden_(True)
            self.prompt_label.setHidden_(True)
            self.prompt_scroll.setHidden_(True)
            self.prompt_hint_label.setHidden_(True)
            self.user_prompt_label.setHidden_(True)
            self.user_prompt_scroll.setHidden_(True)
            self.user_prompt_hint_label.setHidden_(True)
            self.loader.stopAnimation_(None)

        if os.path.exists(protocol_path):
            try:
                with open(protocol_path, "r", encoding="utf-8") as f:
                    self._set_protocol_text(f.read(), parse_markdown=True)
            except Exception as e:
                self._set_protocol_text(tr("main.protocol_read_error", error=e), parse_markdown=False)
        elif status == "processing":
            self._set_protocol_text(tr("main.processing_in_progress"), parse_markdown=False)
        elif status == "recording":
            self._set_protocol_text(tr("main.recording_in_progress"), parse_markdown=False)
        else:
            self._set_protocol_text(tr("main.no_protocol"), parse_markdown=False)

    def numberOfRowsInTableView_(self, _):
        return len(self.recording_files)

    def tableView_objectValueForTableColumn_row_(self, _, __, row):
        if row < 0 or row >= len(self.recording_files):
            return ""
        return self._display_title_for_recording(self.recording_files[row])

    def tableView_viewForTableColumn_row_(self, table, _, row):
        if row < 0 or row >= len(self.recording_files):
            return None

        identifier = "recordingCellView"
        cell = table.makeViewWithIdentifier_owner_(identifier, self)
        if cell is None:
            cell = SidebarRecordingCellView.alloc().initWithFrame_(
                ((0.0, 0.0), (float(table.bounds()[1][0]), float(table.rowHeight() or 34.0)))
            )
            cell.setIdentifier_(identifier)
        filename = self.recording_files[row]
        is_editing_row = (
            self.inline_rename_row == row
            and self.inline_rename_filename == filename
        )

        if is_editing_row:
            cell.setTitle_(self._display_meeting_name(filename))
            cell.text_label.setEditable_(True)
            cell.text_label.setSelectable_(True)
            cell.text_label.setDelegate_(self)
            cell.text_label.setTag_(row)
        else:
            cell.setTitle_(self._display_title_for_recording(filename))
            cell.text_label.setEditable_(False)
            cell.text_label.setSelectable_(False)
            cell.text_label.setDelegate_(None)
        return cell

    def tableView_shouldEditTableColumn_row_(self, _, __, row):
        return bool(self.inline_rename_row == row)

    def tableView_setObjectValue_forTableColumn_row_(self, _, value, __, row):
        if self.inline_rename_in_commit:
            return
        if row < 0 or row >= len(self.recording_files):
            return
        if self.inline_rename_row != row:
            return
        self._finish_inline_rename(str(value) if value is not None else "")

    def tableView_rowViewForRow_(self, _, __):
        return SidebarRecordingRowView.alloc().init()

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

    @objc.python_method
    def focus_recording(self, filename):
        if not filename:
            return
        self._remember_prompt_draft_for_selected()
        self.refresh_file_lists()
        if filename not in self.recording_files:
            return
        self.selected_recording = filename
        self.prompt_loaded_for = None
        idx = self.recording_files.index(filename)
        self.recordings_table.selectRowIndexes_byExtendingSelection_(
            NSIndexSet.indexSetWithIndex_(idx),
            False,
        )
        self.refresh_detail_view()
        self._update_recordings_context_menu_state()

    @objc.python_method
    def start_inline_rename_for_selected(self):
        if not self.selected_recording:
            return
        if self.selected_recording not in self.recording_files:
            return
        self.start_inline_rename_for_row(self.recording_files.index(self.selected_recording))

    @objc.python_method
    def start_inline_rename_for_row(self, row):
        if row < 0 or row >= len(self.recording_files):
            return

        filename = self.recording_files[row]
        status = self._status_for_recording(filename)
        if status == "recording":
            rumps.alert(tr("blocked.title"), tr("blocked.recording"))
            return
        if status == "processing":
            rumps.alert(tr("blocked.title"), tr("blocked.processing"))
            return

        self.inline_rename_row = row
        self.inline_rename_filename = filename
        self.inline_rename_field = None
        self.recordings_table.reloadData()
        self.recordings_table.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(row), False)

        def begin_edit():
            try:
                self.recordings_table.editColumn_row_withEvent_select_(0, row, None, True)
                cell = self.recordings_table.viewAtColumn_row_makeIfNecessary_(0, row, True)
                if cell is not None:
                    field = getattr(cell, "text_label", None)
                    if field is not None:
                        field.setDelegate_(self)
                        field.setTag_(row)
                        self.inline_rename_field = field
            except Exception:
                pass

        self.app.run_on_main(begin_edit)

    @objc.python_method
    def _finish_inline_rename(self, new_value):
        if self.inline_rename_in_commit:
            return
        old_name = self.inline_rename_filename
        if not old_name:
            return
        self.inline_rename_in_commit = True
        self.inline_rename_row = None
        self.inline_rename_filename = None
        self.inline_rename_field = None

        renamed_to = self.app.meetings_service.rename_recording(old_name, new_value)
        if renamed_to:
            old_draft = self.prompt_drafts.pop(old_name, None)
            if old_draft is not None:
                self.prompt_drafts[renamed_to] = old_draft
            old_user_draft = self.user_prompt_drafts.pop(old_name, None)
            if old_user_draft is not None:
                self.user_prompt_drafts[renamed_to] = old_user_draft
            old_template_id = self.template_id_drafts.pop(old_name, None)
            if old_template_id is not None:
                self.template_id_drafts[renamed_to] = old_template_id
            self.selected_recording = renamed_to
            self.prompt_loaded_for = None

        self.refresh_from_state()
        self.refresh_file_lists()
        self.refresh_detail_view()
        self.inline_rename_in_commit = False

    def controlTextDidEndEditing_(self, notification):
        if self.inline_rename_in_commit:
            return
        if self.inline_rename_row is None or not self.inline_rename_filename:
            return
        try:
            field = notification.object()
            if self.inline_rename_field is not None and field != self.inline_rename_field:
                return
            new_value = str(field.stringValue())
        except Exception:
            return
        self._finish_inline_rename(new_value)
