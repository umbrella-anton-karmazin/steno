import logging
import os
import re
import time
import json
import shutil
import subprocess
import tempfile
from datetime import datetime

import rumps
from google import genai
from google.genai import types

from steno_app.config import ConfigManager, DEFAULT_USER_PROMPT, get_selected_prompt_template, get_prompt_template_by_id
from steno_app.i18n import tr


logger = logging.getLogger("Steno")


def _is_invalid_api_key_error(error_text):
    text = (error_text or "").lower()
    return ("api_key_invalid" in text) or ("api key not valid" in text)


def _ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def _is_audio_ext(ext):
    return ext in {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg"}


def _is_video_ext(ext):
    return ext in {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def _normalize_media_for_upload(path):
    """
    Try to normalize media for better upload compatibility.
    Returns (normalized_path, temp_created: bool).
    """
    src = str(path or "")
    if not src or not os.path.exists(src):
        return src, False

    ext = os.path.splitext(src)[1].lower()
    if ext in {".mp4", ".m4a"}:
        return src, False
    if not _ffmpeg_available():
        return src, False

    is_video = _is_video_ext(ext)
    is_audio = _is_audio_ext(ext)
    if not is_video and not is_audio:
        return src, False

    suffix = ".mp4" if is_video else ".m4a"
    fd, normalized_path = tempfile.mkstemp(prefix="steno_norm_", suffix=suffix)
    os.close(fd)

    try:
        if is_video:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                src,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                normalized_path,
            ]
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                src,
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                normalized_path,
            ]

        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not os.path.exists(normalized_path) or os.path.getsize(normalized_path) == 0:
            try:
                os.remove(normalized_path)
            except Exception:
                pass
            return src, False
        return normalized_path, True
    except Exception:
        try:
            os.remove(normalized_path)
        except Exception:
            pass
        return src, False


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


def build_generation_prompts(video_path, config, system_prompt_text=None, user_prompt_text=None):
    meeting_date = get_meeting_date(video_path)
    selected_template = get_selected_prompt_template(config) or {}

    if system_prompt_text is not None:
        system_prompt = str(system_prompt_text).strip()
    else:
        system_prompt = str(selected_template.get("system_prompt") or "").strip()
    if not system_prompt:
        system_prompt = str(config.get("prompt") or "").strip()

    # Important: explicit empty user prompt is valid and should not be replaced.
    # Fallback to default only when no user prompt source was provided at all.
    if user_prompt_text is not None:
        raw_user_prompt = str(user_prompt_text)
    elif "user_prompt" in selected_template:
        raw_user_prompt = str(selected_template.get("user_prompt") or "")
    else:
        raw_user_prompt = DEFAULT_USER_PROMPT

    final_user_prompt = raw_user_prompt.replace("{meeting_date}", meeting_date)
    return system_prompt, final_user_prompt


def build_protocol_metadata(
    video_path,
    mic_audio_path,
    txt_path,
    config,
    template_id,
    system_prompt_text,
    user_prompt_text,
    usage_metadata,
):
    selected_template = get_prompt_template_by_id(config, template_id) or {}
    generated_at = datetime.now().isoformat(timespec="seconds")

    total_tokens = None
    prompt_tokens = None
    candidates_tokens = None
    if usage_metadata:
        try:
            total_tokens = getattr(usage_metadata, "total_token_count", None)
            prompt_tokens = getattr(usage_metadata, "prompt_token_count", None)
            candidates_tokens = getattr(usage_metadata, "candidates_token_count", None)
        except Exception:
            pass

    sources = [os.path.basename(video_path)]
    if mic_audio_path and os.path.exists(mic_audio_path):
        sources.append(os.path.basename(mic_audio_path))

    return {
        "schema_version": 1,
        "protocol_variant": "default",  # foundation for future multi-protocol variants
        "generated_at": generated_at,
        "recording_file": os.path.basename(video_path),
        "protocol_file": os.path.basename(txt_path),
        "template_id": template_id or "",
        "template_name": str(selected_template.get("name") or ""),
        "model_name": str(config.get("model_name") or ""),
        "base_url": str(config.get("base_url") or ""),
        "system_prompt": str(system_prompt_text or ""),
        "user_prompt": str(user_prompt_text or ""),
        "source_files": sources,
        "usage": {
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "candidates_tokens": candidates_tokens,
        },
    }


def write_protocol_metadata(meta_path, metadata):
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        logger.exception("Failed to write protocol metadata: %s", meta_path)
        return False


def process_video_with_ai(
    video_path,
    config,
    app_instance,
    system_prompt_override=None,
    user_prompt_override=None,
    template_id_override=None,
):
    temp_files_to_cleanup = []
    try:
        app_instance.is_processing = True
        app_instance.request_set_state_icon("processing")
        logger.info(f"Starting AI processing logic for: {video_path}")

        api_key = (config.get("api_key") or "").strip()
        if not api_key:
            logger.error("API Key is missing")
            rumps.notification(
                tr("ai.error.title"),
                tr("ai.error.missing_api_key"),
                tr("ai.error.configure_api_key"),
            )
            app_instance.is_processing = False
            app_instance.current_processing_file = None
            app_instance.request_ui_refresh()
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
            logger.exception("File upload failed, trying compatibility normalization")

            normalized_paths = []
            for path in files_to_upload_paths:
                normalized, created = _normalize_media_for_upload(path)
                normalized_paths.append(normalized)
                if created:
                    temp_files_to_cleanup.append(normalized)

            if normalized_paths != files_to_upload_paths:
                logger.info("Retrying upload with normalized media files")
                uploaded_files = []
                retry_error = None
                try:
                    for path in normalized_paths:
                        logger.info(f"Uploading normalized {os.path.basename(path)}...")
                        uf = client.files.upload(file=path)
                        uploaded_files.append(uf)
                except Exception as second_err:
                    retry_error = second_err
                    logger.exception("Upload with normalization failed")

                if retry_error is None:
                    files_to_upload_paths = normalized_paths
                else:
                    raise Exception(f"Ошибка загрузки: {retry_error}")
            else:
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

        selected_template = get_selected_prompt_template(config) or {}
        template_id = str(template_id_override or selected_template.get("id") or "")
        system_instruction, user_prompt_text = build_generation_prompts(
            video_path=video_path,
            config=config,
            system_prompt_text=system_prompt_override,
            user_prompt_text=user_prompt_override,
        )

        # Собираем контент: [File1, File2, ..., UserPrompt(optional)]
        contents = list(ready_files)
        if str(user_prompt_text or "").strip():
            contents.append(user_prompt_text)

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
        meta_path = base_name + "_protocol.meta.json"
        metadata = build_protocol_metadata(
            video_path=video_path,
            mic_audio_path=mic_audio_path,
            txt_path=txt_path,
            config=config,
            template_id=template_id,
            system_prompt_text=system_instruction,
            user_prompt_text=user_prompt_text,
            usage_metadata=getattr(response, "usage_metadata", None),
        )
        write_protocol_metadata(meta_path, metadata)

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
        err_text = str(e)

        def show_error_ui():
            if _is_invalid_api_key_error(err_text):
                rumps.alert(
                    tr("record.api_key_required_title"),
                    f"{tr('ai.error.missing_api_key')}. {tr('ai.error.configure_api_key')}",
                )
                app_instance.set_api_key(None)
            else:
                rumps.alert(
                    tr("ai.error.title"),
                    f"{tr('ai.error.processing_failed')}\n\n{err_text}",
                )

        app_instance.run_on_main(show_error_ui)
        app_instance.request_flash_error()
        app_instance.is_processing = False
        app_instance.current_processing_file = None
        app_instance.request_ui_refresh()
        if app_instance.is_recording:
            app_instance.request_set_state_icon("recording")
        else:
            app_instance.request_set_state_icon("idle")
    finally:
        for path in temp_files_to_cleanup:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
