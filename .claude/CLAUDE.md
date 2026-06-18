# CLAUDE.md

> 项目总纲，每次 Claude Code 会话自动加载。所有代码生成、修改、决策必须首先对齐本文中的目标、约束与禁止项。

---

## 项目目标

构建**多平台电商智能客服系统**，同时服务 **40 个店铺**（覆盖千牛/拼多多/京东/抖音），实现：
- 80% 会话自动回复（FAQ旁路 + LLM兜底）
- 置信度不足自动转人工（硬规则+软阈值）
- 多店铺、多平台会话完全隔离
- 全链路本地化（Obsidian长期记忆、Qdrant向量库、SQLite配置）
- 单服务器集中式部署，低资源占用，零黑盒

---

## 技术栈

- **语言**：Python 3.11+，全异步 `asyncio`
- **消息接入**：千牛TOP API、拼多多开放平台、京麦开放平台、抖店开放平台（Webhook推送）
- **会话热存储**：Redis（键前缀隔离，2h TTL）
- **长期记忆/知识库**：Obsidian（多店铺独立Vault）
- **向量检索**：本地 Qdrant（多Collection隔离）+ 本地 Embedding 模型 `bge-small-zh`
- **LLM**：云端 API（GPT-4o-mini/通义千问/豆包）或本地 Qwen2-7B/14B
- **配置管理**：`pydantic-settings` + `config/settings.yaml` + Redis Pub/Sub 热更新
- **管理后台**（独立服务，非关键路径）：FastAPI + SQLite
- **测试**：pytest + pytest-asyncio
- **代码质量**：black（行宽100）、isort、ruff、mypy

---

## 开发环境

### 必须使用 conda 环境
```bash
conda activate knowledge_qa
```
该环境已包含 Python 3.11 及核心依赖，**所有命令必须在此环境下运行**。

### 初始化项目依赖
```bash
make setup   # 自动安装 requirements.txt 中缺失的包，并初始化本地服务
```
若需要新增依赖，请先更新 `requirements.txt` 再运行 `make setup`。

---

## 核心架构约束（必须遵守）

详细架构见 `.claude/ARCHITECTURE.md`，以下为强制要点：

1. **分层隔离**：接入层 → 调度层 → 检索层 → LLM层 → 动作层，层间仅通过 `contracts/` Pydantic Schema 通信。
2. **平台无关**：调度层、检索层、LLM层 **严禁出现** `if platform == ...` 分支；平台差异仅存在于 `gateway/` 和 `actions/send_message.py`。
3. **多租户隔离**：所有 Redis/Qdrant/Obsidian 必须按 `shop_id` 严格隔离，跨店铺访问视为 bug。
4. **FAQ 缓存优先**：命中 FAQ 缓存（Redis）直接返回，**不调用 LLM、不检索向量库**。
5. **LLM 强制置信度**：回复末尾必须含 `[CONFIDENCE: XX]`，解析失败视为 0。
6. **转人工双通道**：
   - 硬规则（最高优先级）：消息含敏感词（投诉/12315/差评/假货等）直接转人工。
   - 软规则：置信度 < 阈值（默认 85%）且非模糊寒暄 → 转人工。
7. **异常全兜底**：任何步骤失败 → 转人工或安全兜底话术，**不允许会话崩溃**。
8. **记忆回写异步**：Obsidian 写入不得阻塞主回复线程。
9. **全部本地**：向量库、嵌入模型、Obsidian 均在本地，API 密钥仅通过环境变量注入。

---

## 开发命令（通过 Makefile）

所有命令需在 `conda activate knowledge_qa` 后执行：

| 命令 | 说明 |
|------|------|
| `make setup` | 安装依赖、初始化本地 Redis / Qdrant（若未运行） |
| `make run` | 启动客服主程序（所有平台网关 + 调度器） |
| `make test` | 运行全部单元测试与集成测试 |
| `make lint` | 代码格式化与静态检查（ruff + mypy） |
| `make clean` | 清理临时文件、日志、测试缓存 |
| `make dev-server` | 启动管理后台开发服务器（可选，非必须） |

**你必须能够执行这些命令来验证代码修改。**

---

## 关键文件与目录

| 路径 | 用途 |
|------|------|
| `.claude/CLAUDE.md` | 本文件 |
| `.claude/ARCHITECTURE.md` | 完整架构定义、数据流、状态机分支、多平台多店铺设计 |
| `.claude/CONVENTIONS.md` | 编码规范、命名约定、测试要求、超时策略 |
| `src/gateway/` | 多平台消息网关（taobao/pinduoduo/jd/douyin） |
| `src/scheduler/` | 自研状态机核心（≤300行） |
| `src/retrieval/` | FAQ缓存、Obsidian向量检索、元数据召回 |
| `src/llm/` | LLM调用封装、置信度解析 |
| `src/actions/` | 消息发送（平台路由）、人工告警、记忆回写 |
| `src/contracts/` | 所有层间 Pydantic Schema |
| `config/settings.yaml` | 店铺列表、阈值、连接参数 |
| `tests/` | 测试代码（镜像 src 结构） |
| `tests/fixtures/` | 模拟消息、迷你 Obsidian 库等测试数据 |
| `todo.md` | 任务拆分清单，按顺序完成并勾选 |

---

## 绝对禁止

- ❌ 引入 `langchain`、`langgraph`、`llama-index` 或任何通用 Agent 框架。
- ❌ 使用云端向量数据库（Pinecone、Weaviate Cloud）或在线 Embedding 服务。
- ❌ 在核心链路中使用同步阻塞 I/O（如 `time.sleep`、同步 HTTP 客户端）。
- ❌ 将 LLM 原始输出直接发给买家（未经过滤与提取）。
- ❌ 跨层直接访问 Redis/Qdrant/Obsidian 文件系统（必须通过接口）。
- ❌ 跨店铺混合使用 Qdrant Collection、Redis 键、Obsidian Vault。
- ❌ 在日志或回写中暴露手机号、地址等隐私明文。
- ❌ 调度/检索/LLM 代码中出现 `if platform == 'xxx'` 分支。
- ❌ 状态机核心逻辑超过 300 行（不含注释/docstring）。

---

## 开发流程

1. **阅读文档**：动手前先完整阅读 `ARCHITECTURE.md` 和 `CONVENTIONS.md`。
2. **按层实现**：遵循 `todo.md` 顺序，逐层完成并编写对应测试。
3. **契约先行**：新增或修改层间数据结构时，必须同步更新 `contracts/` 中的 Schema 及 `contracts/README.md`。
4. **话术外置**：所有回复买家的文本统一存放在 `config/replies.yaml`，业务代码引用键名。
5. **测试通过**：每一层完成后运行 `make test`，确认通过后再进入下一层。
6. **代码检查**：提交前执行 `make lint`，确保零告警。

---

## 当前项目状态

- 已有：完整架构设计（`ARCHITECTURE.md`）、编码规范（`CONVENTIONS.md`）、Conda 环境 `knowledge_qa`。
- 待办：按 `todo.md` 逐层实现所有模块，从网关层开始。
- 遇到未明确规定的实现细节，参考 `CONVENTIONS.md` 附录默认值，或选择最保守稳定的策略。

---

**你是项目的核心构建者，所有输出必须体现对这些约束的绝对尊重。任何偏离都必须先提出并获得明确同意。**
```