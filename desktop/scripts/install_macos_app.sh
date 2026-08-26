#!/usr/bin/env bash
# Install the built Tauri app and create a macOS Desktop entry.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_BUNDLE="$DESKTOP_DIR/src-tauri/target/release/bundle/macos/LearnFlow.app"
APPLICATIONS_DIR="$HOME/Applications"
INSTALL_PATH="$APPLICATIONS_DIR/LearnFlow.app"
DESKTOP_PATH="$HOME/Desktop/LearnFlow.app"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "找不到已构建的 macOS App：$APP_BUNDLE" >&2
  echo "请先在 desktop 目录运行：npm run build" >&2
  exit 1
fi

mkdir -p "$APPLICATIONS_DIR" "$HOME/Desktop"

backup_path() {
  local target="$1"
  local backup="${target}.backup-$(date +%Y%m%d-%H%M%S)"
  mv "$target" "$backup"
  echo "已有入口已保留为：$backup"
}

if [[ -e "$INSTALL_PATH" || -L "$INSTALL_PATH" ]]; then
  backup_path "$INSTALL_PATH"
fi
ditto "$APP_BUNDLE" "$INSTALL_PATH"

if [[ -e "$DESKTOP_PATH" || -L "$DESKTOP_PATH" ]]; then
  if [[ -L "$DESKTOP_PATH" && "$(readlink "$DESKTOP_PATH")" == "$INSTALL_PATH" ]]; then
    :
  else
    backup_path "$DESKTOP_PATH"
    ln -s "$INSTALL_PATH" "$DESKTOP_PATH"
  fi
else
  ln -s "$INSTALL_PATH" "$DESKTOP_PATH"
fi

open -R "$DESKTOP_PATH"
open "$INSTALL_PATH"
echo "LearnFlow 已安装并启动。"
echo "桌面入口：$DESKTOP_PATH"
