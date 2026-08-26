#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON=""
for candidate in "$ROOT_DIR/backend/venv/bin/python" "$ROOT_DIR/backend/.venv/bin/python"; do
  if [[ -x "$candidate" ]]; then
    PYTHON="$candidate"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "未找到后端虚拟环境，请先运行 make setup。" >&2
  exit 1
fi

PRIVATE_CONFIG="$ROOT_DIR/backend/.private/learning_task_conversion.xfyun.env"
if [[ ! -f "$PRIVATE_CONFIG" ]]; then
  echo "未找到功能私有配置，请先运行 make setup-learning-task-conversion。" >&2
  exit 1
fi

"$PYTHON" - "$PRIVATE_CONFIG" <<'PY'
from pathlib import Path
import sys

required = {
    "XFYUN_APP_ID",
    "XFYUN_API_KEY",
    "XFYUN_API_SECRET",
    "XFYUN_FLOW_ID",
}
values = {}
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip()
missing = sorted(key for key in required if not values.get(key))
if missing:
    raise SystemExit("功能私有配置缺少必填项：" + "、".join(missing))
print("功能私有配置字段完整（未输出密钥值）。")
PY

cd "$ROOT_DIR/backend"
"$PYTHON" -m pytest \
  tests/test_learning_task_conversion_gateway.py \
  tests/test_learning_task_conversion_api.py \
  tests/test_learning_task_conversion_xfyun.py \
  tests/test_architecture_registry.py -q

cd "$ROOT_DIR/frontend"
npm run build

echo "岗位典型工作任务转化模块验证通过。"
