import json
import os
import sys
from copy import deepcopy


CONFIG_FILE = os.path.expanduser("~/.recorder_app_config.json")

def _resolve_assets_dir():
    # py2app runtime: resources are under Steno.app/Contents/Resources
    resource_path = os.environ.get("RESOURCEPATH")
    if resource_path:
        candidate = os.path.join(resource_path, "assets")
        if os.path.isdir(candidate):
            return candidate

    # Generic frozen fallback (e.g. other bundlers).
    if getattr(sys, "frozen", False):
        executable_dir = os.path.dirname(sys.executable)
        candidate = os.path.join(executable_dir, "..", "Resources", "assets")
        candidate = os.path.abspath(candidate)
        if os.path.isdir(candidate):
            return candidate

    # Source mode: src/steno_app/config.py -> src/steno_app/assets
    base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, "assets")


ASSETS_DIR = _resolve_assets_dir()

ICON_IDLE = os.path.join(ASSETS_DIR, "icon_idle.png")
ICON_RECORDING = os.path.join(ASSETS_DIR, "icon_recording.png")
ICON_PROCESSING = os.path.join(ASSETS_DIR, "icon_processing.png")
ICON_ERROR = os.path.join(ASSETS_DIR, "icon_error.png")

AI_MODELS = [
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-flash-lite-latest",
]

DEFAULT_SYSTEM_PROMPT = (
    "Ты — ИИ-ассистент для подготовки протоколов встреч.\n"
    "Верни только результат в Markdown, без вступлений и пояснений.\n"
    "Не выдумывай факты; если данных нет, укажи '-'.\n\n"
    "Структура ответа (соблюдать строго):\n"
    "# Протокол встречи: [Краткая тема]\n"
    "**Дата:** [Дата]\n"
    "**Участники:** [Имена/роли или '-']\n\n"
    "## 1. Саммари (Summary)\n"
    "[Коротко и по сути]\n\n"
    "## 2. Принятые решения\n"
    "* [Конкретные решения]\n\n"
    "## 3. План действий (Action Items)\n"
    "| Задача | Ответственный | Срок |\n"
    "| :--- | :--- | :--- |\n"
    "| [Описание] | [Кто] | [Дата или -] |"
)


DEFAULT_USER_PROMPT = (
    "Составь протокол встречи по приложенным файлам.\n"
    "Дата встречи: {meeting_date}.\n"
    "Укажи участников только если уверенно распознал их по речи."
)

LEGACY_DEFAULT_SYSTEM_PROMPT = (
    "Ты — ИИ-ассистент для составления протоколов встреч. Твоя задача — "
    "проанализировать предоставленный медиафайл и вернуть ТОЛЬКО протокол в формате "
    "Markdown (оптимизированный для Confluence), строго без вступительных слов, "
    "приветствий и пояснений самой нейросети.\n\n"
    "Используй следующий шаблон:\n"
    "# Протокол встречи: [Сформулируй тему]\n"
    "**Дата:** [Дата из запроса]\n"
    "**Участники:** [Список имен или ролей]\n\n"
    "## 1. Саммари (Summary)\n"
    "[Краткое, структурированное содержание обсуждения без воды]\n\n"
    "## 2. Принятые решения\n"
    "* [Список конкретных решений]\n\n"
    "## 3. План действий (Action Items)\n"
    "| Задача | Ответственный | Срок |\n"
    "| :--- | :--- | :--- |\n"
    "| [Описание задачи] | [Имя] | [Дедлайн или -] |"
)

LEGACY_DEFAULT_USER_PROMPT = "Составь протокол по прикрепленному файлу.\n\nДата встречи: {meeting_date}"

LEGACY_TRANSCRIPT_SYSTEM_PROMPT = (
    "Ты — ИИ-ассистент. Проанализируй медиафайл и верни только чистый "
    "транскрипт встречи в Markdown.\n"
    "Структурируй по времени и спикерам.\n"
    "Если спикер не определен, помечай как 'Спикер N'."
)
LEGACY_TRANSCRIPT_USER_PROMPT = (
    "Сделай транскрипт встречи с идентификацией спикеров.\n\n"
    "Дата встречи: {meeting_date}"
)
LEGACY_ANALYSIS_SYSTEM_PROMPT = (
    "Ты — ИИ-ассистент. Проанализируй встречу и верни Markdown-отчет:\n"
    "1) цель и контекст встречи,\n"
    "2) договоренности,\n"
    "3) разногласия/нерешенные вопросы,\n"
    "4) эмоциональный фон участников,\n"
    "5) рекомендации по следующим шагам.\n"
    "Без вводных фраз и без лишних пояснений."
)
LEGACY_ANALYSIS_USER_PROMPT = "Сделай аналитический отчет по встрече.\n\nДата встречи: {meeting_date}"


def _make_default_prompt_templates(system_prompt=None):
    protocol_system = (system_prompt or DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT
    return {
        "templates": [
            {
                "id": "meeting_protocol",
                "name": "Протокол встречи",
                "system_prompt": protocol_system,
                "user_prompt": DEFAULT_USER_PROMPT,
                "built_in": True,
                "archived": False,
            },
            {
                "id": "meeting_transcript",
                "name": "Транскрипт встречи",
                "system_prompt": (
                    "Ты готовишь транскрипт встречи.\n"
                    "Верни только Markdown, без комментариев и интерпретаций.\n"
                    "Сохраняй порядок реплик и помечай спикеров последовательно "
                    "('Спикер 1', 'Спикер 2', ...), если имя не определено.\n\n"
                    "Структура ответа:\n"
                    "# Транскрипт встречи\n"
                    "**Дата:** [Дата]\n\n"
                    "## Транскрипт\n"
                    "- [HH:MM:SS] [Спикер]: [Текст реплики]"
                ),
                "user_prompt": (
                    "Сделай транскрипт встречи с идентификацией спикеров "
                    "по приложенным файлам.\n"
                    "Дата встречи: {meeting_date}."
                ),
                "built_in": True,
                "archived": False,
            },
            {
                "id": "meeting_analysis",
                "name": "Анализ встречи",
                "system_prompt": (
                    "Ты готовишь аналитический отчет по встрече.\n"
                    "Верни только Markdown, без вводных фраз.\n"
                    "Не выдумывай факты; спорные выводы отмечай как гипотезы.\n\n"
                    "Структура ответа:\n"
                    "# Анализ встречи\n"
                    "## 1. О чем встреча\n"
                    "## 2. О чем договорились\n"
                    "## 3. О чем не договорились\n"
                    "## 4. Настрой участников\n"
                    "## 5. Риски и следующие шаги"
                ),
                "user_prompt": (
                    "Сделай анализ встречи по приложенным файлам.\n"
                    "Дата встречи: {meeting_date}.\n"
                    "Нужен фокус на договоренностях, расхождениях и эмоциональном фоне."
                ),
                "built_in": True,
                "archived": False,
            },
        ],
        "selected_template_id": "meeting_protocol",
    }

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://gemini-warmup.galaypro.ru",
    "video_device_idx": "0",
    "video_device_name": "Main Screen",
    "model_name": "gemini-3-flash-preview",
    "prompt": DEFAULT_SYSTEM_PROMPT,
    "save_dir": os.path.expanduser("~/Movies/Steno"),
    "video_quality": "Medium_low_FPS",
    "audio_input_uid": "",
    "audio_input_name": "",
    "used_tokens": 0,
    "last_request_tokens": 0,
    "permissions_onboarding_done": False,
    "hidden_recordings": [],
    "imported_recordings": [],
    "prompt_templates": _make_default_prompt_templates(DEFAULT_SYSTEM_PROMPT),
}

VIDEO_QUALITY_PRESETS = {
    "Low": {"width": 960, "height": 540, "fps": 5, "bitrate": 1000000},
    "Medium_low_FPS": {"width": 1280, "height": 720, "fps": 1, "bitrate": 3000000},
    "Medium": {"width": 1280, "height": 720, "fps": 10, "bitrate": 3000000},
    "High": {"width": 1920, "height": 1080, "fps": 30, "bitrate": 8000000},
    "Ultra": {"width": 2560, "height": 1440, "fps": 60, "bitrate": 25000000}
}


class ConfigManager:
    @staticmethod
    def _upgrade_legacy_builtin_texts(by_id, defaults):
        protocol = by_id.get("meeting_protocol")
        if protocol:
            if protocol.get("system_prompt", "").strip() in {LEGACY_DEFAULT_SYSTEM_PROMPT.strip()}:
                protocol["system_prompt"] = defaults["meeting_protocol"]["system_prompt"]
            if protocol.get("user_prompt", "").strip() in {LEGACY_DEFAULT_USER_PROMPT.strip(), ""}:
                protocol["user_prompt"] = defaults["meeting_protocol"]["user_prompt"]

        transcript = by_id.get("meeting_transcript")
        if transcript:
            if transcript.get("system_prompt", "").strip() in {LEGACY_TRANSCRIPT_SYSTEM_PROMPT.strip()}:
                transcript["system_prompt"] = defaults["meeting_transcript"]["system_prompt"]
            if transcript.get("user_prompt", "").strip() in {LEGACY_TRANSCRIPT_USER_PROMPT.strip(), ""}:
                transcript["user_prompt"] = defaults["meeting_transcript"]["user_prompt"]

        analysis = by_id.get("meeting_analysis")
        if analysis:
            if analysis.get("system_prompt", "").strip() in {LEGACY_ANALYSIS_SYSTEM_PROMPT.strip()}:
                analysis["system_prompt"] = defaults["meeting_analysis"]["system_prompt"]
            if analysis.get("user_prompt", "").strip() in {LEGACY_ANALYSIS_USER_PROMPT.strip(), ""}:
                analysis["user_prompt"] = defaults["meeting_analysis"]["user_prompt"]

    @staticmethod
    def _normalize_prompt_templates(config):
        legacy_prompt = (config.get("prompt") or DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT
        templates_cfg = config.get("prompt_templates")
        defaults = _make_default_prompt_templates(legacy_prompt)

        if not isinstance(templates_cfg, dict):
            config["prompt_templates"] = defaults
            return

        raw_templates = templates_cfg.get("templates")
        if not isinstance(raw_templates, list):
            raw_templates = []

        normalized = []
        seen_ids = set()
        for item in raw_templates:
            if not isinstance(item, dict):
                continue
            template_id = str(item.get("id") or "").strip()
            if not template_id or template_id in seen_ids:
                continue
            seen_ids.add(template_id)
            normalized.append(
                {
                    "id": template_id,
                    "name": str(item.get("name") or template_id).strip() or template_id,
                    "system_prompt": str(item.get("system_prompt") or "").strip(),
                    "user_prompt": str(item.get("user_prompt") or "").strip(),
                    "built_in": bool(item.get("built_in", False)),
                    "archived": bool(item.get("archived", False)),
                }
            )

        if not normalized:
            normalized = defaults["templates"]
        else:
            by_id = {t["id"]: t for t in normalized}
            for built_in in defaults["templates"]:
                if built_in["id"] not in by_id:
                    normalized.append(deepcopy(built_in))
                elif not by_id[built_in["id"]]["system_prompt"].strip():
                    by_id[built_in["id"]]["system_prompt"] = built_in["system_prompt"]
                if by_id[built_in["id"]]["id"] == "meeting_protocol":
                    by_id[built_in["id"]]["system_prompt"] = (
                        by_id[built_in["id"]]["system_prompt"].strip() or legacy_prompt
                    )
            ConfigManager._upgrade_legacy_builtin_texts(
                by_id,
                {t["id"]: t for t in _make_default_prompt_templates(DEFAULT_SYSTEM_PROMPT)["templates"]},
            )

        selected_id = str(templates_cfg.get("selected_template_id") or "").strip()
        valid_ids = {t["id"] for t in normalized if not t.get("archived")}
        if selected_id not in valid_ids:
            selected_id = defaults["selected_template_id"] if defaults["selected_template_id"] in valid_ids else ""
        if not selected_id and valid_ids:
            selected_id = next(iter(valid_ids))

        config["prompt_templates"] = {
            "templates": normalized,
            "selected_template_id": selected_id,
        }

    @staticmethod
    def _normalize_config(config):
        merged = deepcopy(DEFAULT_CONFIG)
        merged.update(config or {})
        ConfigManager._normalize_prompt_templates(merged)
        selected = get_selected_prompt_template(merged)
        merged["prompt"] = selected.get("system_prompt", "") if selected else merged.get("prompt", DEFAULT_SYSTEM_PROMPT)
        return merged

    @staticmethod
    def load():
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    return ConfigManager._normalize_config(loaded)
            except Exception:
                pass
        return ConfigManager._normalize_config({})

    @staticmethod
    def save(config):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(ConfigManager._normalize_config(config), f, indent=4)


def get_prompt_templates(config, include_archived=False):
    templates = list((config.get("prompt_templates") or {}).get("templates") or [])
    if include_archived:
        return templates
    return [item for item in templates if not item.get("archived")]


def get_prompt_template_by_id(config, template_id):
    tid = str(template_id or "").strip()
    for template in get_prompt_templates(config, include_archived=True):
        if template.get("id") == tid:
            return template
    return None


def get_selected_prompt_template(config):
    selected_id = (config.get("prompt_templates") or {}).get("selected_template_id")
    selected = get_prompt_template_by_id(config, selected_id)
    if selected and not selected.get("archived"):
        return selected
    templates = get_prompt_templates(config, include_archived=False)
    return templates[0] if templates else None


def set_selected_prompt_template(config, template_id):
    template = get_prompt_template_by_id(config, template_id)
    if not template or template.get("archived"):
        return False
    config.setdefault("prompt_templates", {})
    config["prompt_templates"]["selected_template_id"] = template["id"]
    config["prompt"] = template.get("system_prompt", "") or config.get("prompt", DEFAULT_SYSTEM_PROMPT)
    return True


def upsert_prompt_template(config, template):
    if not isinstance(template, dict):
        return False
    template_id = str(template.get("id") or "").strip()
    if not template_id:
        return False
    config.setdefault("prompt_templates", {})
    templates = list((config["prompt_templates"].get("templates") or []))
    updated = False
    for idx, existing in enumerate(templates):
        if existing.get("id") == template_id:
            templates[idx] = {**existing, **template, "id": template_id}
            updated = True
            break
    if not updated:
        templates.append(
            {
                "id": template_id,
                "name": str(template.get("name") or template_id),
                "system_prompt": str(template.get("system_prompt") or ""),
                "user_prompt": str(template.get("user_prompt") or ""),
                "built_in": bool(template.get("built_in", False)),
                "archived": bool(template.get("archived", False)),
            }
        )
    config["prompt_templates"]["templates"] = templates
    return True


def archive_prompt_template(config, template_id, archived=True):
    template = get_prompt_template_by_id(config, template_id)
    if not template:
        return False
    template["archived"] = bool(archived)
    if template.get("archived") and (config.get("prompt_templates") or {}).get("selected_template_id") == template["id"]:
        fallback = get_selected_prompt_template(config)
        if fallback:
            config["prompt_templates"]["selected_template_id"] = fallback["id"]
            config["prompt"] = fallback.get("system_prompt", "") or config.get("prompt", DEFAULT_SYSTEM_PROMPT)
    return True


def delete_prompt_template(config, template_id):
    template = get_prompt_template_by_id(config, template_id)
    if not template:
        return False
    if template.get("built_in"):
        return False
    templates = [item for item in get_prompt_templates(config, include_archived=True) if item.get("id") != template["id"]]
    config.setdefault("prompt_templates", {})
    config["prompt_templates"]["templates"] = templates
    if config["prompt_templates"].get("selected_template_id") == template["id"]:
        fallback = get_selected_prompt_template(config)
        if fallback:
            config["prompt_templates"]["selected_template_id"] = fallback["id"]
            config["prompt"] = fallback.get("system_prompt", "") or config.get("prompt", DEFAULT_SYSTEM_PROMPT)
    return True
