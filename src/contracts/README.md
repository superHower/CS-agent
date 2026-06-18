# contracts/ — 跨层数据契约

所有层间通信必须使用本目录中定义的 Pydantic v2 模型，严禁直接传递裸 dict、str 或原始对象。

## 模型清单

| 模型 | 所在文件 | 用途 | 生产层 → 消费层 |
|------|---------|------|----------------|
| `Platform` | models.py | 平台枚举（taobao/pinduoduo/jd/douyin） | 全局 |
| `MessageSource` | models.py | 网关接入方式枚举 | 接入层内部 |
| `SessionState` | models.py | 会话状态枚举 | 调度层 |
| `EscalationReason` | models.py | 转人工原因枚举 | 调度层 → 动作层 |
| `StandardMessage` | models.py | 标准化买家消息 | 接入层 → 调度层 |
| `TurnRecord` | models.py | 单轮对话记录 | 调度层内部 / LLM层 |
| `SessionContext` | models.py | 完整会话上下文（Redis 热存储） | 调度层内部 |
| `KnowledgeChunk` | models.py | 单个知识片段 | 检索层内部 |
| `RetrievalResult` | models.py | 知识检索结果 | 检索层 → 调度层 |
| `LLMRequest` | models.py | LLM 推理输入 | 调度层 → LLM层 |
| `LLMResponse` | models.py | LLM 推理输出 | LLM层 → 调度层 |
| `EscalationContext` | models.py | 转人工上下文 | 调度层 → 动作层 |
| `WritebackTask` | models.py | 记忆回写任务 | 调度层 → 动作层 |

## 强制约束

- 每个模型均配置 `model_config = ConfigDict(extra='forbid')`，拒绝未知字段。
- 所有字段必须使用 `Field(description=...)` 提供文档说明。
- 时间字段统一使用带时区的 `datetime`，以 ISO 8601 字符串序列化。
- 新增或修改模型后，必须同步更新本文件的模型清单。
