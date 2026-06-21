#!/bin/bash
# CS-Agent 一键启动脚本
# 用法：bash start.sh [选项]
#   all       启动全部（主服务 + 后台 API + 前端 UI）[默认]
#   backend   仅启动主服务（客服核心）
#   admin     仅启动管理后台（API + 前端）
#   stop      停止所有 CS-Agent 相关进程

set -euo pipefail

# ── 颜色输出 ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR ]${NC}  $*"; }

# ── 项目根目录（脚本所在位置）──────────────────────────────────────────────────
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

PID_FILE="$ROOT/.cs_agent_pids"

# ── Conda 环境 ─────────────────────────────────────────────────────────────────
CONDA_ENV="knowledge_qa"

activate_conda() {
    # 兼容 conda init 未写入 .bashrc 的情况
    if command -v conda &>/dev/null; then
        eval "$(conda shell.bash hook 2>/dev/null)" || true
        conda activate "$CONDA_ENV" 2>/dev/null || {
            warn "conda activate 失败，尝试直接使用 conda run"
            PYTHON="conda run -n $CONDA_ENV python"
            return
        }
    fi
    PYTHON="python"
}

# ── 依赖检查 ───────────────────────────────────────────────────────────────────
check_redis() {
    if redis-cli ping &>/dev/null; then
        ok "Redis 已运行"
    else
        warn "Redis 未运行，尝试启动..."
        redis-server --daemonize yes --bind 127.0.0.1 --port 6379 --loglevel warning
        sleep 1
        redis-cli ping &>/dev/null && ok "Redis 启动成功" || {
            error "Redis 启动失败，请手动执行: redis-server"
            exit 1
        }
    fi
}

check_qdrant() {
    if curl -sf http://127.0.0.1:6333/healthz &>/dev/null; then
        ok "Qdrant 已运行"
    else
        warn "Qdrant 未运行，尝试 Docker 启动..."
        if command -v docker &>/dev/null; then
            docker run -d --name qdrant_cs_agent \
                -p 6333:6333 -p 6334:6334 \
                -v "$ROOT/data/qdrant:/qdrant/storage" \
                qdrant/qdrant &>/dev/null || true
            sleep 3
            curl -sf http://127.0.0.1:6333/healthz &>/dev/null && ok "Qdrant 启动成功" || {
                error "Qdrant 启动失败，请手动执行: docker run -d -p 6333:6333 qdrant/qdrant"
                exit 1
            }
        else
            error "未找到 Docker，无法自动启动 Qdrant。请手动安装并启动。"
            exit 1
        fi
    fi
}

check_db() {
    if [ ! -f "$ROOT/data/admin.db" ]; then
        info "初始化 SQLite 数据库..."
        $PYTHON -c "
import asyncio, sys
sys.path.insert(0, '.')
from admin.database import init_db
asyncio.run(init_db())
print('数据库初始化完成')
"
        ok "数据库已创建: data/admin.db"
    else
        ok "数据库已存在: data/admin.db"
    fi
}

# ── 启动函数 ───────────────────────────────────────────────────────────────────
start_main_service() {
    info "启动客服主程序..."
    nohup $PYTHON -m src.main \
        > "$LOG_DIR/main.log" 2>&1 &
    echo "main:$!" >> "$PID_FILE"
    ok "客服主程序已启动 (PID $!) | 日志: logs/main.log"
}

start_admin_api() {
    info "启动管理后台 API (port 8080)..."
    nohup $PYTHON -m uvicorn admin.app:app \
        --host 127.0.0.1 --port 8080 \
        > "$LOG_DIR/admin_api.log" 2>&1 &
    echo "admin_api:$!" >> "$PID_FILE"
    sleep 1
    ok "管理后台 API 已启动 (PID $!) | http://localhost:8080/docs"
}

start_admin_ui() {
    if [ ! -d "$ROOT/admin-ui/node_modules" ]; then
        info "安装前端依赖..."
        cd "$ROOT/admin-ui" && npm install --silent
        cd "$ROOT"
    fi
    info "启动管理前端 (port 5173)..."
    nohup bash -c "cd '$ROOT/admin-ui' && npm run dev -- --host" \
        > "$LOG_DIR/admin_ui.log" 2>&1 &
    echo "admin_ui:$!" >> "$PID_FILE"
    sleep 2
    ok "管理前端已启动 (PID $!) | http://localhost:5173"
}

# ── 停止函数 ───────────────────────────────────────────────────────────────────
stop_all() {
    if [ ! -f "$PID_FILE" ]; then
        warn "未找到 PID 文件，尝试按进程名停止..."
        pkill -f "src.main" 2>/dev/null && ok "主程序已停止" || true
        pkill -f "admin.app"  2>/dev/null && ok "管理后台 API 已停止" || true
        pkill -f "vite.*admin-ui" 2>/dev/null && ok "管理前端已停止" || true
        return
    fi
    while IFS=: read -r name pid; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" && ok "已停止 $name (PID $pid)" || warn "停止 $name 失败"
        else
            warn "$name (PID $pid) 已不在运行"
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
    ok "全部进程已停止"
}

# ── 显示状态 ───────────────────────────────────────────────────────────────────
show_summary() {
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║       CS-Agent 启动完成               ║${NC}"
    echo -e "${GREEN}╠═══════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║${NC}  管理后台 API : http://localhost:8080  ${GREEN}║${NC}"
    echo -e "${GREEN}║${NC}  API 文档     : http://localhost:8080/docs ${GREEN}║${NC}"
    echo -e "${GREEN}║${NC}  管理前端     : http://localhost:5173  ${GREEN}║${NC}"
    echo -e "${GREEN}║${NC}  日志目录     : logs/                  ${GREEN}║${NC}"
    echo -e "${GREEN}╠═══════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║${NC}  停止所有: bash start.sh stop          ${GREEN}║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
    echo ""
}

# ── 主流程 ─────────────────────────────────────────────────────────────────────
MODE="${1:-all}"

case "$MODE" in
    stop)
        stop_all
        exit 0
        ;;
    all | backend | admin)
        ;;
    *)
        echo "用法: bash start.sh [all|backend|admin|stop]"
        echo "  all     - 启动全部（主服务 + 后台 API + 前端）[默认]"
        echo "  backend - 仅启动客服主程序"
        echo "  admin   - 仅启动管理后台（API + 前端）"
        echo "  stop    - 停止全部"
        exit 1
        ;;
esac

# 清除旧 PID 文件
rm -f "$PID_FILE"

echo ""
info "CS-Agent 启动中 (模式: $MODE)..."
echo ""

# 激活 conda
activate_conda

# 基础依赖检查
check_redis
check_qdrant
check_db

echo ""

# 按模式启动
case "$MODE" in
    all)
        start_admin_api
        start_admin_ui
        start_main_service
        ;;
    backend)
        start_main_service
        ;;
    admin)
        start_admin_api
        start_admin_ui
        ;;
esac

show_summary
