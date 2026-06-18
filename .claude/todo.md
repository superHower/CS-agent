# TODO.md

> 多平台电商智能客服开发任务清单。
> 请 Claude Code **按顺序逐项完成**，每完成一项勾选 `[x]`，不得跳过或并行执行跨越依赖的任务。

---

## 阶段 0：项目骨架初始化

- [x] 0.1 创建项目顶级目录结构（`src/`, `tests/`, `config/`, `data/`, `models/`, `logs/`, `contracts/` 等，参考 `CONVENTIONS.md`）。
- [x] 0.2 编写 `requirements.txt`，包含所有必需依赖（redis, qdrant-client, sentence-transformers, watchdog, aiohttp, pydantic, pydantic-settings, pytest, pytest-asyncio, black, isort, ruff, mypy 等），并确保 conda 环境 `knowledge_qa` 中已有或补充安装。
- [x] 0.3 创建 `Makefile`，包含 `setup`, `run`, `test`, `lint`, `clean`, `dev-server` 目标，其中 `setup` 负责 `pip install -r requirements.txt`、启动 Redis/Qdrant（若未运行）；`lint` 执行 ruff + mypy。
- [x] 0.4 创建 `config/settings.yaml` 的骨架结构（可先包含一个示例店铺配置），以及 `config/replies.yaml` 空文件。
- [x] 0.5 编写 `src/exceptions.py`，定义 `AppException` 基类和常用子类（如 `GatewayException`, `SendFailedException`, `LLMTimeoutException`）。
- [x] 0.6 创建 `tests/fixtures/` 目录及初始占位文件。

---

## 阶段 1：数据契约层 (`contracts/`)

- [x] 1.1 创建 `src/contracts/` 目录和 `__init__.py`。
- [x] 1.2 按 `ARCHITECTURE.md` 第八节定义所有 Pydantic v2 模型：
  - `StandardMessage`
  - `SessionContext`
  - `RetrievalResult`
  - `LLMRequest` / `LLMResponse`
  - `EscalationContext`
  - `WritebackTask`
- [x] 1.3 每个模型必须包含 `model_config = ConfigDict(extra='forbid')` 和全部字段的 `Field(description=...)`。
- [x] 1.4 编写 `contracts/README.md` 列出所有模型及其用途。
- [x] 1.5 为所有模型编写单元测试（`tests/test_contracts.py`），验证序列化、反序列化、字段验证及 `extra='forbid'` 行为。运行 `make test` 确认通过。

---

## 阶段 2：配置加载与热更新

- [x] 2.1 创建 `src/config/` 包，使用 `pydantic-settings` 加载 `config/settings.yaml`，实现单例配置对象 `Config`。
- [x] 2.2 配置模型需包含 `shops: List[ShopConfig]`，其中 `ShopConfig` 包含 `shop_id`, `platform`, `name`, `api_key`, `api_secret`, `obsidian_vault`, `confidence_threshold` 等字段。
- [x] 2.3 实现 Redis Pub/Sub 监听 `config_updated` 频道，收到消息后重新加载配置并原子化更新单例对象。
- [x] 2.4 编写单元测试：模拟配置更新，验证单例对象同步变化。确保配置热更新过程无竞态。

---

## 阶段 3：日志与工具模块

- [x] 3.1 创建 `src/utils/` 包，实现 `logger.py`：统一配置 `logging`，支持按天轮转、保留30天、格式包含 shop_id 与 trace_id（提供获取/设置 trace_id 的上下文变量工具）。
- [x] 3.2 实现 `src/utils/trace.py`：基于 `contextvars` 的 trace_id 生成与传递工具。
- [x] 3.3 实现 `src/utils/sensitive.py`：提供脱敏函数，对手机号、地址等字段进行掩码处理。
- [x] 3.4 编写对应单元测试。

---

## 阶段 4：网关层——抽象基类与千牛实现

- [x] 4.1 创建 `src/gateway/` 包，定义抽象基类 `BaseGateway`：
  - `async def listen(shop_config: ShopConfig) -> AsyncIterator[StandardMessage]`
  - `async def send(shop_config: ShopConfig, buyer_id: str, content: str, metadata: dict) -> bool`
- [x] 4.2 实现 `src/gateway/taobao.py` —— 千牛 TOP API 网关：
  - 使用 Webhook 监听（HTTP 端点接收推送，转换为 `StandardMessage`）。
  - 实现 `send` 调用 `taobao.qianniu.cloud.message.send`。
  - 消息去重（24小时 `message_id` 去重缓存于 Redis）。
- [x] 4.3 编写千牛网关的单元测试（Mock HTTP 推送与 API 响应），覆盖正常消息、去重、异常重试。
- [x] 4.4 编写一个简单的集成测试：启动一个本地 HTTP 服务器模拟千牛 Webhook，验证消息标准化与发送流程。

---

## 阶段 5：其他平台网关

- [x] 5.1 实现 `src/gateway/pinduoduo.py`（拼多多开放平台推送）。
- [x] 5.2 实现 `src/gateway/jd.py`（京麦开放平台）。
- [x] 5.3 实现 `src/gateway/douyin.py`（抖店开放平台）。
- [x] 5.4 每个网关实现必须与千牛接口完全一致，只做消息格式适配。
- [x] 5.5 为每个网关编写单元测试（Mock 平台推送和发送 API）。
- [x] 5.6 编写多平台消息标准化集成测试：模拟四个平台各推送一条消息，验证全部转化为统一的 `StandardMessage` 且 `shop_id` 正确。

---

## 阶段 6：会话调度层——自研状态机

- [x] 6.1 创建 `src/scheduler/` 包，实现 `SessionScheduler` 类，内部使用 `asyncio.Queue` 接收 `StandardMessage`。
- [x] 6.2 实现 Redis 会话上下文管理：
  - `load_or_create_session(msg) -> SessionContext`
  - `save_session(ctx)`
  - TTL 2 小时自动续期。
- [x] 6.3 实现核心状态机 `dispatch` 函数（≤300 行，实际 223 行）：
  - 分支 1：订单/物流意图识别（预留接口，当前可返回 None 跳过）。
  - 分支 2：FAQ 缓存匹配（调用检索层接口，需等待检索层实现后集成）。
  - 分支 3：硬转人工关键词检查。
  - 分支 4：调用检索层获取知识片段。
  - 分支 5：调用 LLM 推理层生成回复与置信度。
  - 分支 6：置信度与模糊寒暄判定，决定发送或转人工。
  - 分支 7：异常兜底转人工。
- [x] 6.4 实现转人工逻辑：标记 `WAITING_HUMAN`，写入 `pending_alert:{shop_id}`，调用告警模块。
- [x] 6.5 实现会话超时归档：清理 Redis Key，触发异步记忆回写（调用回写模块接口）。
- [x] 6.6 编写单元测试，使用 Mock 替换检索层/LLM层/发送层：
  - 测试 FAQ 命中直接回复
  - 测试敏感词转人工
  - 测试低置信度转人工
  - 测试模糊寒暄兜底
  - 测试异常降级
  - 测试会话超时清理
- [x] 6.7 确保状态机代码无任何平台分支，仅依赖接口。

---

## 阶段 7：知识检索层——Obsidian 混合 RAG

- [x] 7.1 创建 `src/retrieval/` 包，实现 `FaqCache` 类：
  - 使用 Redis 存储 `faq:{shop_id}:{hash}`，支持精确匹配。
  - 提供 `set(faq_id, reply)` 和 `get(normalized_question) -> str`。
- [x] 7.2 实现 Obsidian 向量同步模块 `ObsidianIndexer`：
  - 启动时扫描指定 `obsidian_vault`，将所有 `.md` 文件分段、嵌入、upsert 到 Qdrant `collection_{shop_id}`。
  - 使用 watchdog 监听变更，增量更新（新增/修改 -> upsert，删除 -> remove）。
  - 嵌入模型加载为全局单例（`bge-small-zh` 本地路径 `models/`）。
- [x] 7.3 实现查询增强 `QueryEnhancer`：
  - 加载店铺商品词典（YAML 文件，包含型号缩写到全称的映射）。
  - 改写否定句式（如"不亮" → "故障 不亮"）。
  - 返回增强后的查询字符串列表。
- [x] 7.4 实现检索器 `Retriever`：
  - 分层召回：元数据/标签精确过滤 → 双链笔记加权 → 语义向量 Top5。
  - 综合排序后返回 `RetrievalResult`。
- [x] 7.5 实现记忆回写模块 `src/actions/writeback.py`（虽然属于动作层，但依赖检索层的 Obsidian 操作）：
  - 异步队列处理 `WritebackTask`。
  - 写入对应店铺 `customers/{买家ID}.md`，格式如 `ARCHITECTURE.md` 所述。
  - 脱敏处理。
- [x] 7.6 编写单元测试：
  - FAQ 缓存命中与未命中。
  - 查询增强效果。
  - 向量检索语义匹配（使用迷你 Obsidian 测试库 `tests/fixtures/obsidian/`）。
  - 增量同步正确性（模拟文件增删改）。
  - 记忆回写内容与格式。

---

## 阶段 8：LLM 推理层

- [x] 8.1 创建 `src/llm/` 包，实现 `LLMClient` 抽象，支持云端 API 和本地模型两种后端。
- [x] 8.2 实现云端后端（OpenAI 兼容接口，可配置 GPT-4o-mini / 通义千问 / 豆包）。
- [x] 8.3 实现本地后端（本地 OpenAI 兼容接口调用 Qwen2-7B/14B）。
- [x] 8.4 实现 Prompt 模板引擎：加载模板，填充 `shop_name`、`knowledge`、`history`、`msg`，要求 LLM 输出 `[CONFIDENCE: XX]`。
- [x] 8.5 实现置信度解析（正则提取，失败返回 0）。
- [x] 8.6 编写单元测试：使用 Mock LLM 响应，验证解析、超时处理、模板渲染正确性。

---

## 阶段 9：动作执行层——消息发送、告警

- [x] 9.1 实现 `src/actions/send_message.py`：统一接口，根据 `shop_config.platform` 路由到对应网关的 `send` 方法。
- [x] 9.2 实现发送重试与降级：失败重试 2 次，仍失败写入 `retry_queue:{shop_id}` 和人工待处理队列，触发告警。
- [x] 9.3 实现 `src/actions/alert_human.py`：通过 Webhook 推送钉钉/企业微信告警，包含 shop_id、buyer_id(脱敏)、最后 3 条对话摘要。
- [x] 9.4 编写单元测试：验证平台路由正确、重试逻辑、告警内容格式。

---

## 阶段 10：全链路集成

- [x] 10.1 编写 `src/main.py`：初始化配置、Redis、Qdrant，启动所有网关监听器，启动调度器消费消息。
- [x] 10.2 编写 `Makefile` 的 `run` 目标正确启动主服务。
- [x] 10.3 编写端到端集成测试：使用多店铺 fixture（千牛、拼多多各一个），模拟完整会话流程（FAQ 命中、LLM 置信度高/低、敏感词转人工），验证消息发送和告警输出。
- [x] 10.4 编写压力测试：模拟 40 店铺同时收到消息，验证系统稳定无串话、无崩溃。
- [x] 10.5 编写 Redis 不可用降级测试：关闭 Redis，验证所有消息转人工，系统不崩溃。

---

## 阶段 11：管理后台（独立服务）

- [x] 11.1 使用 FastAPI 创建管理后台应用（`admin/` 目录）。
- [x] 11.2 实现店铺配置 CRUD API（新增/修改/删除店铺），数据存 SQLite。
- [x] 11.3 实现配置变更后推送 Redis `config_updated` 消息。
- [x] 11.4 实现简易仪表盘 API：返回各店铺今日会话数、FAQ 命中率、LLM 调用量等（需主服务统计写入 Redis）。
- [x] 11.5 管理后台不嵌入主服务进程，通过 `make dev-server` 启动。
- [x] 11.6 编写管理后台的单元测试（API 测试）。

---

## 阶段 12：文档与收尾

- [x] 12.1 确保所有模块 docstring 完整。
- [x] 12.2 更新 `ARCHITECTURE.md` 与代码实现一致（如有偏差以代码为准并修正文档）。
- [x] 12.3 运行 `make lint` 通过，零告警。
- [x] 12.4 运行 `make test` 全部通过，覆盖率 ≥ 80%。

---
