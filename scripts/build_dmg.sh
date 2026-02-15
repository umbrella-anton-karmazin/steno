#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# Настройки путей
APP_NAME="${APP_NAME:-Steno}"
APP_PATH="${APP_PATH:-dist/${APP_NAME}.app}"
DMG_NAME="${DMG_NAME:-${APP_NAME}.dmg}"
BACKGROUND_PATH="${BACKGROUND_PATH:-src/steno_app/assets/install.tiff}"

echo "--- Начинаем сборку $APP_NAME ---"

# 1. Проверка наличия приложения
if [ ! -d "$APP_PATH" ]; then
    echo "Ошибка: Файл $APP_PATH не найден!"
    exit 1
fi

# 2. Ad-hoc подпись приложения
echo "1. Подписываем приложение (Ad-hoc)..."
codesign --force --deep -s - "$APP_PATH"

# 3. Удаление старого DMG, если он существует
if [ -f "$DMG_NAME" ]; then
    echo "Удаляем старый $DMG_NAME..."
    rm "$DMG_NAME"
fi

# 4. Создание DMG при помощи create-dmg
echo "2. Создаем установщик DMG..."
create-dmg \
  --volname "$APP_NAME" \
  --background "$BACKGROUND_PATH" \
  --window-pos 200 120 \
  --window-size 512 364 \
  --icon-size 128 \
  --icon "${APP_NAME}.app" 140 170 \
  --hide-extension "${APP_NAME}.app" \
  --app-drop-link 370 170 \
  "$DMG_NAME" \
  "dist/"

echo "--- Сборка завершена! Файл: $DMG_NAME ---"
