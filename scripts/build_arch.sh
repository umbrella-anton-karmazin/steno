#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

APP_NAME="${APP_NAME:-Steno}"
if [ -z "${PYTHON_BIN+x}" ]; then
  PYTHON_BIN="python3"
  PYTHON_BIN_IS_DEFAULT=1
else
  PYTHON_BIN_IS_DEFAULT=0
fi
ARCH="${1:-arm64}"
HOST_ARCH="$(uname -m)"
REQUIRED_PY_PACKAGES="rumps google-genai certifi py2app pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-AVFoundation pyobjc-framework-Quartz pyobjc-framework-ApplicationServices pyobjc-framework-ScreenCaptureKit"

case "$ARCH" in
  arm64|x86_64)
    ;;
  *)
    echo "Usage: $0 [arm64|x86_64]"
    exit 1
    ;;
esac

echo "--- Сборка ${APP_NAME} для ${ARCH} ---"

if [ "$PYTHON_BIN_IS_DEFAULT" -eq 1 ]; then
  if [ "$ARCH" = "arm64" ]; then
    echo "Готовим arm64 окружение (.venv)..."
    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -U pip
    python -m pip install $REQUIRED_PY_PACKAGES
    deactivate
    PYTHON_BIN=".venv/bin/python"
  elif [ "$ARCH" = "x86_64" ] && [ "$HOST_ARCH" = "arm64" ]; then
    echo "Готовим x86_64 окружение (.venv-x86) под Rosetta..."
    if [ -x ".venv-x86/bin/python" ] && ! file .venv-x86/bin/python | grep -q "x86_64"; then
      rm -rf .venv-x86
    fi
    arch -x86_64 /usr/bin/python3 -m venv .venv-x86
    arch -x86_64 zsh -lc ". .venv-x86/bin/activate && python -m pip install -U pip && python -m pip install $REQUIRED_PY_PACKAGES"
    PYTHON_BIN=".venv-x86/bin/python"
  fi
fi

FFMPEG_SOURCE=""
if [ "$ARCH" = "arm64" ]; then
  FFMPEG_SOURCE="bin/ffmpeg_arm64"
elif [ "$ARCH" = "x86_64" ]; then
  FFMPEG_SOURCE="bin/ffmpeg_x86_64"
fi

if [ -n "$FFMPEG_SOURCE" ]; then
  if [ ! -x "$FFMPEG_SOURCE" ]; then
    echo "Ошибка: не найден исполняемый файл $FFMPEG_SOURCE"
    exit 1
  fi
  cp -f "$FFMPEG_SOURCE" bin/ffmpeg
  chmod +x bin/ffmpeg
  if ! file bin/ffmpeg | grep -q "$ARCH"; then
    echo "Ошибка: bin/ffmpeg имеет неверную архитектуру для сборки $ARCH"
    file bin/ffmpeg
    exit 1
  fi
  echo "Используем ffmpeg: $FFMPEG_SOURCE"
fi

rm -rf build dist

if [ "$ARCH" = "x86_64" ] && [ "$HOST_ARCH" = "arm64" ]; then
  if ! file "$PYTHON_BIN" | grep -q "x86_64"; then
    echo "Ошибка: $PYTHON_BIN не является x86_64 Python."
    echo "Удалите .venv-x86 и повторите сборку, либо задайте PYTHON_BIN с x86_64 интерпретатором."
    exit 1
  fi
  arch -x86_64 "$PYTHON_BIN" setup.py py2app --arch "$ARCH"
else
  "$PYTHON_BIN" setup.py py2app --arch "$ARCH"
fi

APP_PATH="dist/${APP_NAME}.app"
if [ ! -d "$APP_PATH" ]; then
  echo "Ошибка: не найдено приложение после сборки: $APP_PATH"
  exit 1
fi

DMG_NAME="${DMG_NAME:-${APP_NAME}-${ARCH}.dmg}"
APP_NAME="$APP_NAME" APP_PATH="$APP_PATH" DMG_NAME="$DMG_NAME" "$SCRIPT_DIR/build_dmg.sh"

echo "--- Готово: ${DMG_NAME} ---"
