.PHONY: start stop restart demo setup setup-learning-task-conversion verify-learning-task-conversion

# ── 启动 ──

start:
	@bash start.sh

stop:
	@bash start.sh stop

restart:
	@bash start.sh restart

demo:
	@bash start.sh demo

# ── 一次配置 ──

setup:
	@echo "==> 配置后端..."
	cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
	@test -f backend/.env || cp backend/.env.example backend/.env
	@echo ""
	@echo "==> 配置前端..."
	cd frontend && npm install
	@echo ""
	@echo "✅ 全部就绪！运行 make start"
	@echo "⚠  别忘了编辑 backend/.env 填入 API Key"

# ── 岗位典型工作任务转化（功能私有配置，不进入全局 .env） ──

setup-learning-task-conversion:
	@bash scripts/setup_learning_task_conversion.sh

verify-learning-task-conversion:
	@bash scripts/verify_learning_task_conversion.sh

# ── 开发帮助 ──

backend-logs:
	tail -f backend/app.log 2>/dev/null || echo "No log file"

lint:
	cd frontend && npx tsc --noEmit
	cd backend && source venv/bin/activate && python -m py_compile app/**/*.py 2>/dev/null || true
