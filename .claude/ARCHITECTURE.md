# ARCHITECTURE.md

> 本文件定义项目的完整分层架构、模块职责、数据流向与核心实现约束。  
> Claude Code 在编写任何代码前，必须首先通读本文件；所有模块必须严格对齐本文中的分层与契约。

---

## 一、项目定位与终极目标

- **定位**：多平台电商智能客服，同时服务 **40个店铺**，覆盖 **千牛（淘宝/天猫）、拼多多、京东、抖音商城** 四大平台。
- **终极目标**：
  1. 稳定自动回复（80% 会话无需人工参与）。
  2. 置信度不足自动转人工。
  3. 多买家、多店铺、多平台会话完全隔离。
  4. 低资源占用、全链路可控、无黑盒。
  5. 长期记忆与知识库全部本地化（Obsidian），数据不出本机/内网。
  6. 单服务器集中式部署，承载全部 40 店铺。

---

## 二、总体分层架构（自上而下）

```
接入层：多平台消息网关
  ├─ 千牛网关 (taobao)
  ├─ 拼多多网关 (pinduoduo)
  ├─ 京东网关 (jd)
  └─ 抖音网关 (douyin)
        ↓
会话调度层：自研轻量异步状态机 (替代LangGraph)
        ↓
知识检索层：Obsidian混合RAG (FAQ缓存 + 向量检索 + 元数据召回)
        ↓
LLM推理层：生成回复 + 输出置信度分数
        ↓
动作执行层：平台消息发送、人工告警、Obsidian记忆回写
```

- **层级间通信**：通过 `contracts/` 中定义的 Pydantic Schema 传递，严禁裸 dict。
- **依赖方向**：上层依赖下层，禁止反向调用或跨层直接访问底层存储（如 Redis/Qdrant/Obsidian文件系统）。
- **平台差异隔离原则**：只有“接入层”和“动作层的发送模块”感知平台差异，其余三层（调度、检索、LLM）完全通用。

---

## 三、接入层：多平台消息网关

### 职责
- 监听四大平台的买家消息，将其转换为统一内部格式 `StandardMessage`。
- 兼容各平台 Webhook/消息推送机制，向上提供统一接口。
- 对每个店铺启动独立监听实例，消息标注 `shop_id` 和 `platform`。

### 统一消息格式
所有平台消息标准化为：
```python
class StandardMessage(BaseModel):
    shop_id: str          # 全局唯一店铺ID，如 "tb_lamp_001"
    platform: str         # "taobao" | "pinduoduo" | "jd" | "douyin"
    buyer_id: str         # 平台内买家ID
    content: str          # 消息文本
    timestamp: datetime   # 带时区
    message_id: str       # 平台消息ID，用于幂等去重
    raw_metadata: dict    # 各平台特有字段（如抖音的飞鸽会话ID），不参与业务逻辑
```

### 各平台接入方式

| 平台 | 接入方式 | 网关模块 |
|------|---------|---------|
| 千牛（淘宝/天猫） | TOP API 消息推送 Webhook | `src/gateway/taobao.py` |
| 拼多多 | 开放平台消息推送（需订阅） | `src/gateway/pinduoduo.py` |
| 京东 | 京麦开放平台消息推送 + API | `src/gateway/jd.py` |
| 抖音商城 | 抖店开放平台 Webhook | `src/gateway/douyin.py` |

每个网关模块必须实现：
- `async def listen(shop_config) -> AsyncIterator[StandardMessage]`：启动监听，持续产出标准化消息到统一队列。
- `async def send(shop_config, buyer_id, content, metadata)`：发送回复（由动作层调用）。

### 接入约束
- 所有平台统一走 **官方 API 推送**，不采用本地数据库监听等兜底方案（多平台多店铺场景下无法维护）。
- 同一平台下多个店铺，各自独立实例化网关（通过配置驱动）。
- 网关层严禁做业务判断、意图识别或会话逻辑，只做消息格式转换与去重（按 `message_id` 幂等）。
- 消息去重窗口：24 小时。

---

## 四、会话调度层：自研轻量异步状态机

### 职责
- 为每个 `(shop_id, buyer_id)` 维护独立会话上下文（存入 Redis），会话间完全隔离。
- 实现固定流转分支（详见下文），替代通用框架的冗余状态序列化。
- 会话超时自动归档，控制 Redis 内存占用。

### 多租户隔离策略
- Redis 键命名规范：`{业务前缀}:{shop_id}:{实体ID}`
  - 会话上下文：`session:{shop_id}:{buyer_id}`
  - FAQ 缓存：`faq:{shop_id}:{问题hash}`
  - 人工待处理队列：`pending_alert:{shop_id}`
- 所有键设置 TTL（会话 2 小时，FAQ 缓存 24 小时），防止冷数据堆积。
- `shop_id` 全局唯一，建议命名规则：`{平台缩写}_{类目}_{序号}`，如 `tb_lamp_001`、`pdd_bag_002`。

### 会话上下文（Redis 热存储）
- 结构：`SessionContext` Pydantic 对象，包含：
  - `shop_id`
  - `platform`
  - `buyer_id`
  - 最近 N 轮对话历史（每轮 `{role, content, time}`）
  - 当前待处理消息
  - 检索到的知识片段
  - 置信度分数
  - 当前状态：`ACTIVE | WAITING_HUMAN | ENDED`
- TTL：2 小时无活动自动过期，视为会话结束并触发异步归档。

### 固定流转分支（必须严格执行）
状态机仅包含以下 **7 条分支**，核心逻辑总代码量 ≤ 300 行 Python（不含注释/docstring）：

1. **新消息入队** → 创建/续期 Redis 会话上下文（按 `shop_id + buyer_id` 查找）。
2. **订单/物流查询意图** → 调用平台 API 获取订单/物流实时状态 → 直接拼装回复模板（不经过 LLM）。
3. **命中 FAQ 精确缓存** → 直接返回预置回复，跳过 LLM 与向量检索。
4. **未命中 FAQ** → 调用知识检索层获取对应店铺的 Obsidian 知识片段。
5. **送入 LLM 生成回复 + 置信度打分** → 根据分数与规则分流：
   - **置信度 ≥ 阈值（默认85%）且未命中敏感词硬规则** → 自动发送回复。
   - **置信度 < 阈值但属于模糊寒暄**（如“在吗”“你好”）→ 发送安全兜底话术，不转人工。
   - **置信度 < 阈值（其他情况）或命中必须转人工关键词** → 直接转人工，触发告警。
6. **任何分支执行异常** → 立即降级为转人工，不得导致会话阻塞。
7. **会话超时/结束** → 归档上下文，清理 Redis Key，触发异步记忆回写。

### 转人工规则（双通道判定，通用化）
- **硬规则（优先级最高）**：买家消息包含 `[投诉, 12315, 工商, 差评, 曝光, 赔偿, 假货, 退款, 举报]` 任一关键词，无论置信度如何，必须转人工。
- **软规则**：置信度低于阈值（每个店铺可单独配置）且不满足模糊寒暄条件 → 转人工。
- 转人工动作：
  - 会话状态标记为 `WAITING_HUMAN`。
  - 写入人工待处理队列 `pending_alert:{shop_id}`。
  - 推送告警到钉钉/企业微信（附带 shop_id、buyer_id、最后 N 条对话）。

### 约束
- 状态机核心逻辑与平台无关，不出现任何 `if platform == "taobao"` 分支。
- 严禁使用第三方状态机框架（`transitions`、`automaton` 等）。
- 所有 Redis 操作必须设置超时与重试，Redis 不可用时降级为“所有消息转人工”，系统不崩溃。

---

## 五、知识检索层：Obsidian 混合 RAG（按店铺隔离）

### 职责
- 以 Obsidian 笔记库为唯一长期知识源，每个店铺拥有独立的 `Obsidian Vault` 和 `Qdrant Collection`。
- 提供多级检索能力，不依赖任何云端向量或 Embedding 服务。

### 多店铺知识隔离
- Obsidian 库路径：`{base_path}/{shop_id}/`（如 `/data/obsidian/tb_lamp_001/`）。
- Qdrant Collection：`collection_{shop_id}`，每个店铺独立，检索时根据 `shop_id` 选择对应 Collection。
- FAQ 缓存：`faq:{shop_id}:{问题hash}`，Redis 前缀隔离。

### 检索优先级（由快到严，逐级降级）
1. **FAQ 精确缓存（最高优先级）**  
   - 存储于 Redis，键为 `faq:{shop_id}:{问题标准化hash}`。
   - 命中直接返回对应回复，无需任何模型调用。
2. **Obsidian 元数据/标签/双链加权召回**  
   - 基于商品型号、售后分类等 frontmatter/标签进行精确过滤。
   - 将双链关联笔记提升权重。
3. **本地向量语义检索（兜底）**  
   - 使用 `bge-small-zh` 本地嵌入模型 + Qdrant 本地向量库。
   - 返回语义相似度 Top5 片段。

### 查询增强（必须实现）
- 在向量检索前，对用户原始消息进行 **查询改写**：
  - 型号缩写展开（如 “A款” → “A款吸顶灯”，依赖店铺级商品词典）。
  - 否定句式改写（如 “不亮” → “故障 不亮”），避免语义漂移。
- 改写逻辑基于正则 + 词典，不调用大模型。
- 每个店铺可拥有独立的商品词典。

### 数据同步（Obsidian → Qdrant）
- 使用 watchdog 监听各店铺 Obsidian 库文件夹（`.md` 文件变更）。
- 增量更新对应店铺的 Qdrant Collection：新增/修改自动重新分段、嵌入、upsert；删除自动移除。
- 启动时执行一次全量同步校验，确保向量库与文件系统一致。
- 同步任务按店铺独立进行，互不阻塞。

### Obsidian 回写（记忆沉淀）
- 每轮会话结束后，异步生成结构化对话总结，写入对应店铺的 `customers/{买家ID}.md`。
- 文件结构：
  ```markdown
  # 买家昵称
  ## YYYY-MM-DD
  - 咨询问题与意图分类 → 已解决/转人工
  - 关键商品/标签双链
  ```
- 同一天内多次咨询追加到同一日期块下；新一天创建新日期块。
- 回写过程不得阻塞消息回复主线程，失败重试 3 次后降级记录错误日志。

### 约束
- 向量库只允许使用本地 Qdrant（容器化或二进制），禁止连接任何云端实例。
- 嵌入模型必须离线下载到本地 `models/` 目录，不发起任何外部网络请求。
- 所有检索操作总耗时必须 < 300ms（P99），超出时直接使用 FAQ 缓存或固定兜底回复。
- 跨店铺知识隔离为硬约束，任何模块不得跨店铺检索知识或混用 Qdrant Collection。

---

## 六、LLM 推理层

### 职责
- 接收统一格式的 `LLMRequest`（用户消息 + 会话上下文 + 检索到的知识片段 + shop_id）。
- 生成回复与置信度分数，返回 `LLMResponse`。
- 与平台、店铺无关，纯推理模块。

### 固定输入模板
- 必须使用项目配置的 prompt 模板，强制要求 LLM 在回复末尾输出 `[CONFIDENCE: XX]`（0-100 整数）。
- 模板示例（简化）：
  ```
  你是{shop_name}的客服，基于以下知识回复用户。回复末尾必须给出置信度：[CONFIDENCE: 数值]。
  知识：{retrieved_knowledge}
  对话历史：{history}
  用户消息：{msg}
  ```
- `shop_name` 从配置注入，用于增强回复准确性。
- 解析逻辑使用正则提取置信度，解析失败视为置信度=0。

### 模型适配
- 支持两种模式，通过配置切换：
  - **云端 API**：GPT-4o-mini / 通义千问 / 豆包
  - **本地离线**：Qwen2-7B/14B 私有化部署（通过兼容 OpenAI 接口的本地服务）
- 所有模型调用必须设置超时（默认 5 秒），超时视为生成失败，触发转人工。

### 约束
- 严禁将 LLM 输出直接发送给买家，必须经过置信度过滤与敏感词二次校验。
- 每次调用必须记录 input tokens、output tokens、耗时，用于按店铺统计成本。

---

## 七、动作执行层

### 职责
- 封装所有“对外产生效果”的操作，与业务逻辑解耦。
- 除“消息发送”外，其余模块与平台无关。

### 模块1：平台消息发送客户端
- 统一接口：`async def send_message(shop_id: str, buyer_id: str, content: str) -> bool`
- 内部根据店铺配置的 `platform` 路由到对应网关的发送方法：
  ```python
  async def send_message(shop_id, buyer_id, content):
      shop = shop_config[shop_id]
      if shop.platform == "taobao":
          return await taobao_sender.send(...)
      elif shop.platform == "pinduoduo":
          return await pdd_sender.send(...)
      # ...
  ```
- 发送失败自动重试（最多 2 次），仍失败则写入 `retry_queue:{shop_id}` 后台重试队列，并写入人工待处理队列告警。

### 模块2：人工告警推送
- 接口：`async def alert_human(escalation_context: EscalationContext)`
- 包含：`shop_id`, `buyer_id`, `platform`, 最近 N 条聊天记录, 触发原因（置信度不足/关键词/异常）。
- 推送目标：钉钉机器人 Webhook 或企业微信应用消息（通过全局配置指定，所有店铺共用告警通道）。
- 告警消息格式必须简洁，附带 `shop_id + buyer_id`（脱敏）与最后 3 条对话摘要。

### 模块3：Obsidian 记忆回写服务
- 实现为独立异步任务队列（内建 `asyncio.Queue`），不阻塞主流程。
- 接收 `WritebackTask`（含 `shop_id`, `buyer_id`, 对话总结, 标签等），按前文规则写入对应店铺的 Obsidian 库。
- 写入前必须对敏感信息（手机号、地址等）进行脱敏。

### 约束
- 三个模块必须独立编写，互不依赖，仅通过接口调用。
- 任何动作执行失败都不得引发主状态机崩溃。
- 消息发送模块的平台路由必须基于配置驱动，新增平台时仅需增加一个 `elif` 分支，无需改动其他代码。

---

## 八、数据契约（`contracts/`）

所有跨层数据必须使用 `contracts/` 中定义的 Pydantic v2 模型，核心 Schema：

| Schema | 字段 | 用途 |
|--------|------|------|
| `StandardMessage` | shop_id, platform, buyer_id, content, timestamp, message_id, raw_metadata | 标准化买家消息 |
| `SessionContext` | shop_id, buyer_id, history, state, pending_msg, knowledge, confidence | Redis 会话上下文 |
| `RetrievalResult` | fragments: list[{content, source, score}] | 检索返回的知识片段 |
| `LLMRequest` | shop_id, msg, history, knowledge | 推理层输入 |
| `LLMResponse` | reply, confidence, tokens_used, latency_ms | 推理层输出 |
| `EscalationContext` | shop_id, buyer_id, platform, reason, history | 转人工上下文 |
| `WritebackTask` | shop_id, buyer_id, summary, tags, timestamp | 记忆回写任务 |

**强制要求**：
- 每个 Schema 必须包含 `model_config = ConfigDict(extra='forbid')` 以拒绝未知字段。
- 所有字段使用 `Field(description=...)`。
- 新增或修改 Schema 必须同步更新 `contracts/README.md`。

---

## 九、多店铺配置管理

### 配置结构（`config/settings.yaml`）
```yaml
shops:
  - shop_id: "tb_lamp_001"
    platform: "taobao"
    name: "灯具旗舰店"
    api_key: "${TB_LAMP_KEY}"
    api_secret: "${TB_LAMP_SECRET}"
    obsidian_vault: "/data/obsidian/tb_lamp_001"
    confidence_threshold: 85
  - shop_id: "pdd_bag_002"
    platform: "pinduoduo"
    name: "箱包专营店"
    api_key: "${PDD_BAG_KEY}"
    api_secret: "${PDD_BAG_SECRET}"
    obsidian_vault: "/data/obsidian/pdd_bag_002"
    confidence_threshold: 80
  # ... 共40个店铺
```

### 配置热加载
- 客服服务启动时从配置文件或管理后台加载全部店铺配置。
- 配置变更时，通过 Redis Pub/Sub 推送 `config_updated` 事件，客服服务热更新，无需重启。
- 管理后台独立部署，通过读写配置数据库（SQLite）提供可视化编辑界面，但不介入消息处理链路。

---

## 十、部署架构

```
                 互联网
                   │
    ┌──────────────┼──────────────┬──────────────┐
    ▼              ▼              ▼              ▼
 千牛Webhook   拼多多Webhook   京东Webhook   抖音Webhook
    │              │              │              │
    └──────────────┴──────────────┴──────────────┘
                   │
                   ▼
         ┌─────────────────┐
         │  Nginx (可选)   │
         │  统一Webhook入口 │
         └────────┬────────┘
                  │
                  ▼
         ┌─────────────────────────────┐
         │   客服主服务 (单进程异步)     │
         │   - 4平台网关监听器×40店铺   │
         │   - 调度器 + 状态机          │
         │   - 知识检索层 (连接Qdrant)  │
         │   - LLM推理                 │
         │   - 动作执行                │
         │   服务器: 8C16G 单机         │
         └──────┬──────────────────────┘
                │
         ┌──────┴──────┐
         │             │
         ▼             ▼
       Redis        Qdrant
    (会话/FAQ缓存)  (40个Collection)
         │
         ▼
      SQLite (管理配置)
```

- 资源预算：40 店铺，8C16G 单服务器稳定承载。
- Redis/Qdrant 绑定 `127.0.0.1`，不暴露公网。
- API 密钥全部通过环境变量注入，禁止硬编码。

---

## 十一、对比通用框架的核心优势

1. **性能**：无序列化冗余，单实例并发远高于 LangGraph，内存占用极低。
2. **全可控**：所有分支手写代码，状态机 ≤ 300 行，可随时扩展新平台/新功能。
3. **平台无关**：新增平台仅需实现两个接口（listen + send），核心逻辑零改动。
4. **Obsidian 深度适配**：原生支持标签/双链/增量同步/结构化回写，按店铺分库。
5. **生产稳定**：内置会话隔离、熔断、降级转人工、异常兜底。
6. **极致低成本**：FAQ 缓存削峰 80% LLM 调用，本地向量库零费用，SQLite 零维护。

---

## 十二、绝对禁止（跨所有层）

- ❌ 引入任何通用 Agent 框架（`langchain`、`langgraph`、`llama-index` 等）。
- ❌ 使用云端向量数据库或在线 Embedding 服务。
- ❌ 在核心链路中使用同步阻塞 I/O。
- ❌ 将 LLM 原始输出直接发给买家。
- ❌ 跨层直接访问 Redis/Qdrant/Obsidian 文件系统。
- ❌ 在日志或回写中暴露买家手机号、地址等隐私明文。
- ❌ 在调度层或检索层出现任何平台特定逻辑（`if platform == ...`）。
- ❌ 状态机核心逻辑超过 300 行。
- ❌ 跨店铺混用 Qdrant Collection、Redis 键、Obsidian 库。
```