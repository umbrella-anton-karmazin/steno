import logging
import os
import re
import time
from datetime import datetime

import rumps
from google import genai
from google.genai import types

from steno.config import ConfigManager
from steno.i18n import tr


logger = logging.getLogger("Steno")


def get_meeting_date(filename):
    """
    Алгоритм получения даты встречи:
    1. Из названия файла (Meet_YYYY-MM-DD_HH-MM-SS.mp4)
    2. Дата изменения файла
    3. Дата создания файла
    4. Текущая дата
    """
    # 1. Попытка распарсить из имени файла
    # Ожидаемый формат от рекордера: Meet_DD.MM.YYYY_HH:MM:SS.mp4
    basename = os.path.basename(filename)
    match = re.search(r"Meet_(\d{2}\.\d{2}\.\d{4})_", basename)
    if match:
        return match.group(1)

    # 2. Дата изменения
    try:
        mtime = os.path.getmtime(filename)
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    except Exception:
        pass

    # 3. Дата создания
    try:
        ctime = os.path.getctime(filename)
        return datetime.fromtimestamp(ctime).strftime("%Y-%m-%d")
    except Exception:
        pass

    # 4. Текущая дата
    return datetime.now().strftime("%Y-%m-%d")


def process_video_with_ai(video_path, config, app_instance, prompt_override=None):
    try:
        app_instance.is_processing = True
        app_instance.request_set_state_icon("processing")
        logger.info(f"Starting AI processing logic for: {video_path}")

        api_key = config.get("api_key")
        if not api_key:
            logger.error("API Key is missing")
            rumps.notification(
                tr("ai.error.title"),
                tr("ai.error.missing_api_key"),
                tr("ai.error.configure_api_key"),
            )
            app_instance.is_processing = False
            if app_instance.is_recording:
                app_instance.request_set_state_icon("recording")
            else:
                app_instance.request_set_state_icon("idle")
            return

        # 1. Определяем файлы для загрузки
        # Основное видео + микрофон (MP4)
        files_to_upload_paths = [video_path]

        # Ищем файл микрофона (M4A)
        # Он должен лежать рядом с именем: имя_файла_mic.m4a
        base_name = os.path.splitext(video_path)[0]
        mic_audio_path = base_name + "_mic.m4a"

        if os.path.exists(mic_audio_path):
            logger.info(f"Found microphone audio track: {mic_audio_path}")
            files_to_upload_paths.append(mic_audio_path)
        else:
            logger.warning("Microphone audio file not found, processing video only.")

        # 2. Инициализация клиента
        client_kwargs = {"api_key": api_key}
        base_url = config.get("base_url", "").strip()
        if base_url:
            if not base_url.startswith(("http://", "https://")):
                base_url = "https://" + base_url
            client_kwargs["http_options"] = {"baseUrl": base_url}

        client = genai.Client(**client_kwargs)

        rumps.notification(
            tr("ai.processing.title"),
            tr("ai.processing.uploading"),
            tr("ai.processing.files_count", count=len(files_to_upload_paths)),
        )

        # 3. Загрузка всех файлов
        uploaded_files = []
        try:
            for path in files_to_upload_paths:
                logger.info(f"Uploading {os.path.basename(path)}...")
                uf = client.files.upload(file=path)
                uploaded_files.append(uf)
        except Exception as upload_err:
            logger.exception("File upload failed")
            raise Exception(f"Ошибка загрузки: {upload_err}")

        # 4. Ожидание процессинга ВСЕХ файлов
        ready_files = []
        for uf in uploaded_files:
            logger.info(f"Waiting for processing: {uf.name} ({uf.display_name})")
            while uf.state.name == "PROCESSING":
                time.sleep(3)
                uf = client.files.get(name=uf.name)

            if uf.state.name == "FAILED":
                logger.error(f"Google failed to process file {uf.name}")
                raise Exception(f"Google не смог обработать файл {uf.display_name}")

            ready_files.append(uf)
            logger.info(f"File ready: {uf.name}")

        # 5. Генерация контента
        logger.info(f"Generating protocol with model: {config.get('model_name')}")

        # Формируем жесткий User Prompt с датой
        meeting_date = get_meeting_date(video_path)
        user_prompt_text = f"Составь протокол по прикрепленному файлу.\n\nДата встречи: {meeting_date}"

        # Системный промпт: берем итоговый текст из UI (если передан), иначе из конфига.
        system_instruction = (prompt_override or config.get("prompt", "")).strip() or config.get("prompt", "")

        # Собираем контент: [File1, File2, ..., UserPrompt]
        contents = ready_files + [user_prompt_text]

        response = client.models.generate_content(
            model=config.get("model_name"),
            contents=contents,
            config=types.GenerateContentConfig(
                http_options={"timeout": 600000},
                system_instruction=system_instruction,
            ),
        )

        # --- Token Usage Tracking ---
        if response.usage_metadata:
            total_tokens = response.usage_metadata.total_token_count
            config["used_tokens"] = config.get("used_tokens", 0) + total_tokens
            config["last_request_tokens"] = total_tokens
            ConfigManager.save(config)
            try:
                app_instance.run_on_main(app_instance.update_token_stats)
            except Exception as e:
                logger.warning(f"Failed to update token stats in UI: {e}")
        # ----------------------------

        txt_path = base_name + "_protocol.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(response.text)

        logger.info(f"Protocol saved to: {txt_path}")

        # 6. Удаление файлов из облака
        for uf in ready_files:
            try:
                client.files.delete(name=uf.name)
                logger.info(f"Remote file deleted: {uf.name}")
            except Exception as delete_err:
                logger.warning(f"Could not delete remote file: {delete_err}")

        rumps.notification(
            tr("ai.done.title"),
            tr("ai.done.protocol_saved"),
            tr("ai.done.file_name", filename=os.path.basename(txt_path)),
        )
        app_instance.is_processing = False
        app_instance.current_processing_file = None
        app_instance.request_ui_refresh()

        if app_instance.is_recording:
            app_instance.request_set_state_icon("recording")
        else:
            app_instance.request_set_state_icon("idle")

    except Exception as e:
        logger.exception("AI worker failed")
        rumps.notification(tr("ai.error.title"), tr("ai.error.processing_failed"), str(e)[:50])
        app_instance.request_flash_error()
        app_instance.is_processing = False
        app_instance.current_processing_file = None
        app_instance.request_ui_refresh()
        if app_instance.is_recording:
            app_instance.request_set_state_icon("recording")
        else:
            app_instance.request_set_state_icon("idle")

