import locale as py_locale
import os

from steno.config import ASSETS_DIR


try:
    from Foundation import NSLocale

    HAS_NSLOCALE = True
except Exception:
    HAS_NSLOCALE = False


I18N_DIR = os.path.join(ASSETS_DIR, "i18n")


def _parse_flat_yaml(path):
    data = {}
    if not os.path.exists(path):
        return data

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue

            if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                value = value[1:-1]
                value = value.replace("\\n", "\n").replace("\\t", "\t")
                value = value.replace('\\"', '"').replace("\\\\", "\\")
            elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
                value = value[1:-1].replace("''", "'")
            else:
                if " #" in value:
                    value = value.split(" #", 1)[0].rstrip()
            data[key] = value
    return data


def _detect_system_language():
    candidates = []

    if HAS_NSLOCALE:
        try:
            languages = NSLocale.preferredLanguages()
            if languages:
                candidates.append(str(languages[0]))
        except Exception:
            pass

    for env_name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)

    try:
        loc = py_locale.getlocale()[0]
        if loc:
            candidates.append(loc)
    except Exception:
        pass

    for candidate in candidates:
        normalized = str(candidate).strip().lower()
        if normalized.startswith("ru"):
            return "ru"
        if normalized.startswith("en"):
            return "en"
    return "en"


class Localizer:
    def __init__(self, i18n_dir):
        self.i18n_dir = i18n_dir
        self.lang = _detect_system_language()
        self.fallback = _parse_flat_yaml(os.path.join(self.i18n_dir, "en.yaml"))
        self.active = _parse_flat_yaml(os.path.join(self.i18n_dir, f"{self.lang}.yaml"))

    def translate(self, key, **kwargs):
        text = self.active.get(key, self.fallback.get(key, key))
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text


LOCALIZER = Localizer(I18N_DIR)


def tr(key, **kwargs):
    return LOCALIZER.translate(key, **kwargs)

