#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE_DIR="$ROOT_DIR/backend/.private"
TARGET="$PRIVATE_DIR/learning_task_conversion.xfyun.env"
EXAMPLE="$ROOT_DIR/backend/.private.example/learning_task_conversion.xfyun.env.example"

mkdir -p "$PRIVATE_DIR"
chmod 700 "$PRIVATE_DIR"

if [[ ! -f "$TARGET" ]]; then
  cp "$EXAMPLE" "$TARGET"
  chmod 600 "$TARGET"
  echo "已创建功能私有配置：backend/.private/learning_task_conversion.xfyun.env"
  echo "请填写讯飞 App ID、API Key、API Secret 和 Flow ID；该文件已被 gitignore。"
else
  chmod 600 "$TARGET"
  echo "功能私有配置已存在，未覆盖：backend/.private/learning_task_conversion.xfyun.env"
fi
