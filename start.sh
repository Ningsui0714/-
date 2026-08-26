#!/usr/bin/env bash
# LearnFlow 一键启动脚本
# 使用: bash start.sh         (启动 + 自动打开浏览器)
#       bash start.sh demo    (隔离数据库 + 离线比赛演示)
#       bash start.sh stop   (停止)

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PERSONALIZED_DIR="$ROOT_DIR/integrations/wf04"
VENV_DIR="$BACKEND_DIR/venv"
REGULAR_PID_FILE="/tmp/learnflow-pids"
DEMO_PID_FILE="/tmp/learnflow-demo-pids"
PID_FILE="$REGULAR_PID_FILE"
BACKEND_PORT=8010
FRONTEND_PORT=5173
PERSONALIZED_PORT=4174
PERSONALIZED_DATABASE="backend/data/learning_app.db"
OPEN_URL="http://localhost:$FRONTEND_PORT"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

banner() {
  echo -e "${BLUE}"
  echo "  _                   _____ _                "
  echo " | |   ___  ___ __ _|  ___| | _____      __ "
  echo " | |  / _ \/ __/ _\` | |_  | |/ _ \ \ /\ / /"
  echo " | |_|  __/ (_| (_| |  _| | | (_) \ V  V / "
  echo " |_____\___|\___\__,_|_|   |_|\___/ \_/\_/  "
  echo -e "${NC}"
  echo -e "${GREEN}AI 驱动的自适应学习平台${NC}"
  echo ""
}

check_deps() {
  if [ ! -x "$VENV_DIR/bin/python" ] && [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
    VENV_DIR="$BACKEND_DIR/.venv"
  fi
  # Python + venv
  if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo -e "${YELLOW}⚠  后端 venv 不存在，正在创建...${NC}"
    cd "$BACKEND_DIR"
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt
    echo -e "${GREEN}✅ 后端依赖安装完成${NC}"
  fi

  # .env
  if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo -e "${YELLOW}⚠  未找到 .env，从 .env.example 复制${NC}"
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo -e "${YELLOW}⚠  请编辑 backend/.env 填入你的 LLM_API_KEY${NC}"
  fi

  # 个性化学习内容引擎使用独立私密配置。首次启动只复制安全
  # 占位模板；CONTENT_LLM_API_KEY 留空时明确降级为确定性模板。
  if [ ! -f "$PERSONALIZED_DIR/backend/.env" ]; then
    cp "$PERSONALIZED_DIR/backend/.env.example" "$PERSONALIZED_DIR/backend/.env"
    echo -e "${YELLOW}⚠  已创建个性化学习配置；填写 CONTENT_LLM_API_KEY 后使用 DeepSeek${NC}"
  fi

  # Node modules
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo -e "${YELLOW}⚠  前端依赖未安装，正在安装...${NC}"
    cd "$FRONTEND_DIR"
    npm install --silent
    echo -e "${GREEN}✅ 前端依赖安装完成${NC}"
  fi
}

prepare_competition_demo() {
  local demo_data_dir="$BACKEND_DIR/data"
  local demo_database="$demo_data_dir/competition-demo.db"
  mkdir -p "$demo_data_dir"
  export COMPETITION_DEMO_MODE=true
  export DATABASE_URL="sqlite+aiosqlite:///$demo_database"
  export LLM_API_KEY=""
  export GITHUB_RESOURCE_SEARCH_ENABLED=false
  export MEMORY_AUTO_SYNTHESIS_ENABLED=false
  PID_FILE="$DEMO_PID_FILE"
  BACKEND_PORT="$(next_available_port 8010)"
  FRONTEND_PORT="$(next_available_port 5173)"
  PERSONALIZED_PORT="$(next_available_port 4174)"
  PERSONALIZED_DATABASE="backend/data/competition-demo.db"
  export VITE_API_PROXY="http://127.0.0.1:$BACKEND_PORT"
  OPEN_URL="http://localhost:$FRONTEND_PORT/demo"

  echo -e "${BLUE}━━━ 初始化离线比赛演示 ━━━${NC}"
  cd "$BACKEND_DIR"
  "$VENV_DIR/bin/python" scripts/seed_competition_demo.py --reset
  echo -e "${GREEN}✅ 演示数据已就绪（独立数据库，不影响日常数据）${NC}"
}

next_available_port() {
  local candidate="$1"
  while command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$candidate" -sTCP:LISTEN >/dev/null 2>&1; do
    candidate=$((candidate + 1))
  done
  printf '%s' "$candidate"
}

stop_pid_file() {
  local target_pid_file="$1"
  [ -f "$target_pid_file" ] || return 1
  local pid
  while read -r pid; do
    case "$pid" in
      ''|*[!0-9]*) continue ;;
    esac
    if [ "$pid" -gt 1 ]; then
      kill "$pid" 2>/dev/null || true
    fi
  done < "$target_pid_file"
  rm -f "$target_pid_file"
  return 0
}

stop_previous_demo() {
  if stop_pid_file "$DEMO_PID_FILE"; then
    echo -e "${GREEN}✅ 已停止上一份比赛演示实例${NC}"
  fi
}

start_services() {
  : > "$PID_FILE"
  if [ -f "$PERSONALIZED_DIR/backend/server.py" ]; then
    PERSONALIZED_PORT="$(next_available_port "$PERSONALIZED_PORT")"
    export PERSONALIZED_LEARNING_IMPORT_URL="http://127.0.0.1:$PERSONALIZED_PORT/api/integrations/learning-task-knowledge"
    echo -e "${BLUE}━━━ 启动个性化学习运行时 (端口 $PERSONALIZED_PORT) ━━━${NC}"
    cd "$PERSONALIZED_DIR"
    APP_HOST=127.0.0.1 \
      APP_PORT="$PERSONALIZED_PORT" \
      APP_DATABASE="$PERSONALIZED_DATABASE" \
      APP_SEED_DEMO=0 \
      "$VENV_DIR/bin/python" backend/server.py --host 127.0.0.1 --port "$PERSONALIZED_PORT" &
    PERSONALIZED_PID=$!
    echo $PERSONALIZED_PID >> "$PID_FILE"
  else
    echo -e "${YELLOW}⚠  未找到个性化学习运行时，知识点交接启动将不可用${NC}"
  fi

  echo -e "${BLUE}━━━ 启动后端 (端口 $BACKEND_PORT) ━━━${NC}"
  cd "$BACKEND_DIR"
  source "$VENV_DIR/bin/activate"
  uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
  BACK_PID=$!
  echo $BACK_PID >> "$PID_FILE"

  echo -e "${BLUE}━━━ 启动前端 (端口 $FRONTEND_PORT) ━━━${NC}"
  cd "$FRONTEND_DIR"
  npm run dev -- --port "$FRONTEND_PORT" --strictPort &
  FRONT_PID=$!
  echo $FRONT_PID >> "$PID_FILE"

  echo ""
  echo -e "${GREEN}✅ LearnFlow 已启动！${NC}"
  echo ""
  echo -e "   ${BLUE}前端:${NC}  http://localhost:$FRONTEND_PORT"
  echo -e "   ${BLUE}后端:${NC}  http://localhost:$BACKEND_PORT"
  if [ -n "${PERSONALIZED_PID:-}" ]; then
    echo -e "   ${BLUE}个性化学习:${NC}  http://localhost:$PERSONALIZED_PORT"
  fi
  echo ""
  echo -e "   ${YELLOW}停止:${NC}  bash start.sh stop"
  echo ""

  # Auto-open browser after a short delay
  (sleep 3 && open "$OPEN_URL") &
}

stop_services() {
  local found=false
  local target_pid_file
  for target_pid_file in "$REGULAR_PID_FILE" "$DEMO_PID_FILE"; do
    if [ ! -f "$target_pid_file" ]; then
      continue
    fi
    found=true
    echo -e "${YELLOW}正在停止 LearnFlow...${NC}"
    stop_pid_file "$target_pid_file"
  done
  if [ "$found" = true ]; then
    echo -e "${GREEN}✅ 已停止${NC}"
  else
    pkill -f "uvicorn app.main:app" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
    pkill -f "integrations/wf04/backend/server.py" 2>/dev/null || true
    pkill -f "backend/server.py --host 127.0.0.1 --port 4174" 2>/dev/null || true
    echo -e "${GREEN}✅ 已停止 (清理模式)${NC}"
  fi
}

case "${1:-}" in
  stop)
    stop_services
    ;;
  restart)
    stop_services
    sleep 1
    banner
    check_deps
    start_services
    ;;
  demo)
    banner
    stop_previous_demo
    check_deps
    prepare_competition_demo
    start_services
    ;;
  *)
    banner
    check_deps
    start_services
    ;;
esac
