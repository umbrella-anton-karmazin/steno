import json
import os
import sys


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

    # Source mode: steno/config.py -> project root/assets
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://gemini-warmup.galaypro.ru",
    "video_device_idx": "0",
    "video_device_name": "Main Screen",
    "model_name": "gemini-3-flash-preview",
    "prompt": "Ты — ИИ-ассистент для составления протоколов встреч. Твоя задача — проанализировать предоставленный медиафайл и вернуть ТОЛЬКО протокол в формате Markdown (оптимизированный для Confluence), строго без вступительных слов, приветствий и пояснений самой нейросети.\n\nИспользуй следующий шаблон:\n# Протокол встречи: [Сформулируй тему]\n**Дата:** [Дата из запроса]\n**Участники:** [Список имен или ролей]\n\n## 1. Саммари (Summary)\n[Краткое, структурированное содержание обсуждения без воды]\n\n## 2. Принятые решения\n* [Список конкретных решений]\n\n## 3. План действий (Action Items)\nОформи строго как таблицу:\n| Задача | Ответственный | Срок |\n| :--- | :--- | :--- |\n| [Описание задачи] | [Имя] | [Дедлайн или -] |",
    "save_dir": os.path.expanduser("~/Movies/Steno"),
    "video_quality": "Medium",
    "used_tokens": 0,
    "last_request_tokens": 0,
    "permissions_onboarding_done": False,
    "hidden_recordings": [],
}

VIDEO_QUALITY_PRESETS = {
    "Low": {"width": 960, "height": 540, "fps": 5, "bitrate": 1000000},
    "Medium": {"width": 1280, "height": 720, "fps": 10, "bitrate": 3000000},
    "High": {"width": 1920, "height": 1080, "fps": 30, "bitrate": 8000000},
    "Ultra": {"width": 2560, "height": 1440, "fps": 60, "bitrate": 25000000}
}


class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    return {**DEFAULT_CONFIG, **loaded}
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    @staticmethod
    def save(config):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
