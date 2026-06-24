.PHONY: setup run test lint clean dev-server dev-ui

PYTHON := python
PIP := pip
SRC := src
TESTS := tests

setup:
	@echo ">>> 安装依赖..."
	$(PIP) install -r requirements.txt
	@echo ">>> 检查 Redis..."
	@redis-cli ping > /dev/null 2>&1 || (echo "Redis 未运行，尝试启动..." && redis-server --daemonize yes --bind 127.0.0.1 --port 6379)
	@echo ">>> 检查 Qdrant..."
	@curl -sf http://127.0.0.1:6333/healthz > /dev/null 2>&1 || echo "⚠️  Qdrant 未运行，请手动启动: docker run -d -p 6333:6333 qdrant/qdrant"
	@echo ">>> setup 完成"

run:
	@echo ">>> 启动客服主程序..."
	$(PYTHON) -m src.main

test:
	@echo ">>> 运行测试..."
	$(PYTHON) -m pytest $(TESTS) -v --cov=$(SRC) --cov-report=term-missing --asyncio-mode=auto

lint:
	@echo ">>> ruff 检查..."
	ruff check $(SRC) $(TESTS)
	@echo ">>> mypy 类型检查..."
	mypy $(SRC) --ignore-missing-imports
	@echo ">>> black 格式检查..."
	black --check --line-length 100 $(SRC) $(TESTS)
	@echo ">>> lint 通过"

format:
	@echo ">>> 格式化代码..."
	isort $(SRC) $(TESTS)
	black --line-length 100 $(SRC) $(TESTS)
	ruff check --fix $(SRC) $(TESTS)

clean:
	@echo ">>> 清理临时文件..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml 2>/dev/null || true
	@echo ">>> 清理完成"

dev-server:
	@echo ">>> 启动服务 (port 8080)..."
	$(PYTHON) -m uvicorn "src.main:create_app()" --host 127.0.0.1 --port 8080 --reload --factory

dev-ui:
	@echo ">>> 启动管理后台前端 (port 5173)..."
	cd admin-ui && npm run dev
