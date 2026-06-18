# CONVENTIONS.md

> 本文件为项目编码规范、命名约定与测试要求，适用于多平台多店铺架构。  
> Claude Code 必须在每次写代码时严格遵守，任何偏离必须提前说明并获确认。

---

## 1. 语言与运行环境
- Python 3.11+，全链路使用 `asyncio` 异步编程。
- 虚拟环境统一使用 `.venv`，依赖锁定在 `requirements.txt`。
- 所有常用操作通过项目根目录 `Makefile` 提供：`make setup`、`make run`、`make test`、`make lint`、`make clean`。

## 2. 项目结构约定
```
src/
├── gateway/          # 多平台消息网关
│   ├── base.py       # 抽象网关接口
│   ├── taobao.py     # 千牛(淘宝/天猫)
│   ├── pinduoduo.py  # 拼多多
│   ├── jd.py         # 京东
│   └── douyin.py     # 抖音
├── scheduler/        # 自研轻量异步状态机
├── retrieval/        # Obsidian 混合RAG检索（按shop_id隔离）
├── llm/              # LLM推理层
├── actions/          # 动作执行层
│   ├── send_message.py   # 平台消息发送客户端（统一路由）
│   ├── alert_human.py    # 人工告警推送
│   └── writeback.py      # Obsidian记忆回写
├── contracts/        # 跨层Pydantic数据模型
├── utils/            # 通用工具（日志、配置加载等）
├── config/           # 配置定义与加载（pydantic-settings）
├── tests/            # 测试代码镜像 src 结构
└── data/             # 本地持久化数据（Qdrant存储、Obsidian库路径配置等）
```
- 模块间依赖：上层只能导入同层或下层模块，禁止反向依赖。
- `contracts/` 中的数据模型是唯一的层间通信格式，任何层不得绕过 Schema 直接传递 dict、str 或原始对象。

## 3. 多店铺与多平台原则
- 所有核心业务逻辑（调度、检索、LLM）**不得出现平台特定分支**（`if platform == 'taobao'` 等），平台差异仅体现在 `gateway/` 和 `actions/send_message.py` 中。
- 店铺唯一标识 `shop_id` 必须贯穿所有数据模型与 Redis/Qdrant 键，格式推荐：`{平台缩写}_{类目}_{序号}`（例如 `tb_lamp_001`）。
- 知识库与缓存严格按店铺隔离：
  - Redis 键：`{业务前缀}:{shop_id}:{实体ID}`
  - Qdrant Collection：`collection_{shop_id}`
  - Obsidian 路径：`{base_path}/{shop_id}/`
- 绝不允许跨店铺访问知识库、缓存或会话数据。

## 4. 编码风格
- 遵循 PEP 8，使用 `black`（行宽 100）、`isort` 排序导入、`ruff` 做 linting。
- 所有公开函数/方法必须包含类型注解（参数与返回值），并使用 `mypy` 静态检查。
- 异步代码统一使用 `async def` 和 `await`，禁止在协程中调用同步阻塞函数；必要时用 `asyncio.to_thread` 包装。
- 不允许使用 `*args` / `**kwargs` 除非在装饰器或明确代理场景；接口参数必须显式声明。

## 5. 命名约定
- **模块/文件**：`snake_case`，如 `session_context.py`。
- **类**：`PascalCase`，如 `SessionScheduler`。
- **函数/方法**：`snake_case`，如 `get_faq_cache()`。
- **常量**：`UPPER_SNAKE_CASE`，如 `DEFAULT_CONFIDENCE_THRESHOLD`。
- **私有成员**：单下划线前缀，如 `_redis_client`。
- **Redis/缓存键**：统一前缀，冒号分隔，格式 `{业务域}:{shop_id}:{标识符}`，例如 `session:tb_lamp_001:buyer_123`。
- **Qdrant Collection**：统一前缀 `collection_` 加 `shop_id`，如 `collection_tb_lamp_001`。

## 6. 数据规范与 Schema 强制
- 所有层间数据交换必须基于 `contracts/` 中的 Pydantic v2 BaseModel。
- 每个 Schema 强制配置 `model_config = ConfigDict(extra='forbid')`。
- 所有字段必须使用 `Field(description=...)` 添加文档说明。
- 日期时间字段统一使用带时区的 `datetime`，并以 ISO 8601 字符串序列化。
- 中文内容统一 UTF-8 编码；日志与注释允许中文。
- 新增 Schema 必须同步更新 `contracts/README.md` 中的清单。

## 7. 错误处理与降级
- 所有外部调用（网络请求、文件 I/O、数据库操作）必须有明确异常捕获与重试策略。
- 自定义异常定义在 `src/exceptions.py`，继承自统一基类 `AppException`。
- 严禁使用裸 `except:`，必须指定具体异常类型。
- 消息发送失败必须降级：进入 `retry_queue:{shop_id}` 后台重试，并写入人工待处理队列，触发告警。
- 状态机任意步骤异常不得导致会话崩溃，必须回退到转人工安全状态。
- Redis 不可用时，所有消息直接转人工，系统不崩溃。
- 任何网络或存储超时必须设置合理上限（默认值在 `CONVENTIONS.md` 附录给出，代码中可通过配置覆盖）。

## 8. 日志规范
- 使用标准库 `logging`，通过配置文件控制级别与格式；禁止使用 `print` 输出运行时信息。
- 日志级别约定：
  - `DEBUG`：开发调试细节
  - `INFO`：关键流程节点（消息接收、检索开始、LLM调用、发送结果、配置热更新）
  - `WARNING`：可恢复异常、降级、阈值边界、重试
  - `ERROR`：不可恢复但已捕获的异常、人工告警触发
- 每条日志必须携带 `shop_id` 和可追踪的会话标识（如 `buyer_id` 脱敏值或内部 trace_id）。
- 日志输出到 `logs/` 目录，按天轮转，保留 30 天。

## 9. 测试要求
- 测试框架：`pytest` + `pytest-asyncio`。
- 每层核心逻辑必须有单元测试，覆盖率目标 ≥ 80%。
- 集成测试必须覆盖一条完整跨平台会话生命周期：消息接入 → 调度 → 检索 → LLM回复 → 发送/转人工。
- 关键边界测试场景：
  - 不同平台消息标准化与去重
  - FAQ 缓存命中与未命中
  - 置信度高于/低于阈值
  - 敏感词硬转人工规则
  - 模糊寒暄兜底话术
  - 会话超时自动归档
  - 平台消息发送失败重试
  - Obsidian 增量同步与向量库一致性
  - 多店铺知识严格隔离（跨店铺检索必须返回空）
  - Redis 不可用降级
- 所有测试必须可独立运行，不依赖任何外部真实服务（千牛/拼多多/京东/抖音/钉钉），使用 mock 或本地 fixture 替代。
- 测试数据统一放在 `tests/fixtures/`，按店铺拆分目录，模拟多店铺场景。

## 10. 严禁引入的依赖与模式
- **禁止**引入任何通用 Agent 框架：`langchain`、`langgraph`、`llama-index` 等。
- **禁止**使用云端向量数据库（Pinecone、Weaviate Cloud 等），仅允许本地 Qdrant。
- **禁止**在线 Embedding 服务，嵌入模型必须离线本地加载。
- **禁止**在核心链路中使用同步阻塞 I/O（文件读写除外，但需在异步线程中执行）。
- **禁止**将大模型输出直接发送给买家，必须经置信度过滤与敏感词二次校验。
- **禁止**在 Obsidian 回写操作中阻塞消息回复主线程，必须异步执行。
- **禁止**在调度层、检索层、LLM推理层出现任何平台或店铺硬编码常量。

## 11. 安全与隐私
- 买家手机号、详细地址等敏感信息不得出现在日志、数据库值或回写内容中，必须脱敏（掩码中间四位，或使用统一的脱敏工具函数）。
- 所有本地持久化服务（Redis、Qdrant）只能绑定 `127.0.0.1` 或内网 IP，禁止监听 `0.0.0.0`。
- 各平台 API 密钥/Secret 只能通过环境变量注入，严禁硬编码在源码或配置文件中。
- Obsidian 笔记库路径通过店铺配置指定，不允许使用绝对路径写死。

## 12. 配置管理
- 所有可配置项（阈值、超时、连接字符串、路径等）统一放在 `config/settings.yaml`，使用 `pydantic-settings` 加载并校验。
- 多店铺配置通过列表定义，每项包含：`shop_id`、`platform`、`api_key`（环境变量引用）、`obsidian_vault`、`confidence_threshold` 等。
- 配置热更新：主服务通过 Redis Pub/Sub 监听 `config_updated` 频道，收到消息后重新加载配置，无需重启。
- 配置读写必须线程/协程安全，更新操作原子化。

## 13. 文档与注释
- 每个模块（`.py` 文件）顶部必须包含一行简要说明模块职责。
- 所有公共函数/类必须包含 Google 风格 docstring（中文或英文均可，但项目内统一）。
- 复杂业务逻辑（状态机分支、检索优先级、查询改写）必须有行内注释说明意图，禁止留下“魔法数字”。
- 外部接口/非直观算法必须附带 example 或参考链接。
- 架构文档与代码不一致时，以本文件及 `ARCHITECTURE.md` 为准，并及时更新文档。

## 14. 默认超时与重试策略（附录）
| 操作 | 默认超时 | 重试次数 | 备注 |
|------|---------|---------|------|
| 平台消息发送 | 3s | 2 | 失败后进入 retry_queue |
| LLM API 调用 | 5s | 0 | 超时转人工 |
| 向量检索 | 300ms (P99) | 0 | 超时用兜底回复 |
| Redis 操作 | 1s | 1 | 失败降级转人工 |
| Obsidian 回写 | 5s | 3 | 失败记录错误日志 |
| 管理配置 API 调用 | 2s | 1 | 失败使用本地缓存 |

---

**以上约定等同于架构约束，Claude Code 在生成任何代码时必须逐条遵守，违反任一条款视为不合格交付。**
```