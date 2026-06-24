import { useState } from "react";
import { Title, useNotify } from "react-admin";
import { Button, Card, Collapse, Input, Space, Tag, Typography, Spin } from "antd";
import { SendOutlined, CheckCircleOutlined, CloseCircleOutlined, RightOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";

const { TextArea } = Input;
const { Text } = Typography;

const DEFAULT_HISTORY_ITEM = JSON.stringify({
  platform: "淘宝",
  shop: "艾睿斯旗舰店",
  buyer: "测试买家",
  product: "客厅吸顶灯2026新款超薄LED",
  chatList: [
    "6月21日10:33\n机器人接待中",
    "这个灯直径多少\n6月21日10:33:26"
  ],
  detail: "无"
}, null, 2);

interface StepInfo {
  step: string;
  label: string;
  hit?: boolean;
  reply?: string;
  error?: string;
  elapsed_ms?: number;
  intent?: string;
  entities?: string[];
  rewrite_query?: string;
  faq_hit?: boolean;
  faq_reply?: string;
  chunks_count?: number;
  chunks?: { content: string; score: number | null }[];
  confidence?: number;
  knowledge_chars?: number;
}

interface DebugResult {
  shop_id: string;
  shop_name: string;
  extracted_buyer: string;
  extracted_message: string;
  history_turns_count: number;
  product_name: string;
  steps: StepInfo[];
  final_source?: string;
  final_reply?: string;
  escalated?: boolean;
  confidence?: number;
  confidence_threshold?: number;
  total_elapsed_ms?: number;
  error?: string;
}

const SOURCE_LABELS: Record<string, string> = {
  faq_cache: "FAQ 直接命中",
  intent_rag: "意图识别 + RAG",
  fallback: "兜底（转人工）",
};

function StepCard({ step }: { step: StepInfo }) {
  const hasError = !!step.error;
  const borderColor = hasError ? "#ff4d4f" : step.hit === false ? "#faad14" : "#52c41a";

  return (
    <div style={{
      border: `1px solid ${borderColor}`,
      borderRadius: 6,
      padding: "12px 16px",
      background: "#fafafa",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <Tag color={hasError ? "error" : step.hit === false ? "warning" : "success"} style={{ margin: 0 }}>
          {step.label}
        </Tag>
        {step.elapsed_ms !== undefined && (
          <Text type="secondary" style={{ fontSize: 12 }}>{step.elapsed_ms}ms</Text>
        )}
      </div>

      {step.step === "faq_cache" && (
        <div>
          {step.hit ? (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#52c41a", marginBottom: 4 }}>
                <CheckCircleOutlined /> <Text strong>命中！直接返回缓存回复</Text>
              </div>
              <div style={{ background: "#f6ffed", padding: "8px 12px", borderRadius: 4, whiteSpace: "pre-wrap" }}>
                {step.reply}
              </div>
            </>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#faad14" }}>
              <CloseCircleOutlined /> <Text>未命中，继续下一步</Text>
              {step.error && <Text type="danger" style={{ fontSize: 12 }}>（错误: {step.error}）</Text>}
            </div>
          )}
        </div>
      )}

      {step.step === "intent" && !hasError && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div><Text type="secondary">意图：</Text><Tag>{step.intent || "未识别"}</Tag></div>
          {step.entities && step.entities.length > 0 && (
            <div><Text type="secondary">实体：</Text>{step.entities.map((e, i) => <Tag key={i}>{e}</Tag>)}</div>
          )}
          {step.rewrite_query && (
            <div><Text type="secondary">改写查询：</Text><Text code>{step.rewrite_query}</Text></div>
          )}
        </div>
      )}

      {step.step === "rag" && !hasError && (
        <div>
          <div style={{ marginBottom: 6 }}>
            <Text type="secondary">检索到 </Text>
            <Text strong>{step.chunks_count}</Text>
            <Text type="secondary"> 条知识片段</Text>
          </div>
          {step.chunks && step.chunks.length > 0 && (
            <Collapse ghost size="small" items={step.chunks.map((c, i) => ({
              key: i,
              label: <Text style={{ fontSize: 12 }}>片段 {i + 1}{c.score != null ? `（相似度: ${c.score.toFixed(3)}）` : ""}</Text>,
              children: <pre style={{ fontSize: 11, whiteSpace: "pre-wrap", margin: 0, color: "#555" }}>{c.content}</pre>,
            }))} />
          )}
        </div>
      )}

      {step.step === "llm" && !hasError && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div>
            <Text type="secondary">置信度：</Text>
            <Tag color={step.confidence != null && step.confidence >= 85 ? "success" : "warning"}>
              {step.confidence ?? "N/A"}
            </Tag>
            {step.knowledge_chars !== undefined && (
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                知识上下文 {step.knowledge_chars} 字符
              </Text>
            )}
          </div>
          <div style={{ background: "#f0f5ff", padding: "8px 12px", borderRadius: 4, whiteSpace: "pre-wrap" }}>
            {step.reply}
          </div>
        </div>
      )}

      {hasError && (
        <Text type="danger" style={{ fontSize: 12 }}>错误: {step.error}</Text>
      )}
    </div>
  );
}

export default function MessageTest() {
  const notify = useNotify();
  const [historyItemRaw, setHistoryItemRaw] = useState(DEFAULT_HISTORY_ITEM);
  const [parseError, setParseError] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DebugResult | null>(null);

  const validateHistoryItem = (val: string): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(val);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
      if (!Array.isArray(parsed.chatList)) return null;
      return parsed as Record<string, unknown>;
    } catch {
      return null;
    }
  };

  const handleHistoryChange = (val: string) => {
    setHistoryItemRaw(val);
    const parsed = validateHistoryItem(val);
    setParseError(parsed === null ? '请输入合法的 JSON 对象，需包含 chatList 字段' : "");
  };

  const handleSend = async () => {
    const historyItem = validateHistoryItem(historyItemRaw);
    if (!historyItem) { setParseError("请输入合法的 JSON 对象，需包含 chatList 字段"); return; }

    if (!historyItem.shop) { notify("缺少 shop 字段", { type: "warning" }); return; }

    setLoading(true);
    setResult(null);

    try {
      const res = await fetch(`${apiUrl}/debug/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(historyItem),
      });
      const data = await res.json();
      if (!res.ok) {
        notify(`请求失败: ${data.detail ?? res.statusText}`, { type: "error" });
      } else {
        setResult(data as DebugResult);
      }
    } catch (e) {
      notify(`网络错误: ${e}`, { type: "error" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 900 }}>
      <Title title="消息测试" />
      <Card title="发送测试消息" extra="模拟影刀 RPA 推送消息，查看完整处理 Pipeline">
        <Space direction="vertical" style={{ width: "100%" }} size={16}>
          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>
              History 条目（RPA history 数组中的单个元素）
            </div>
            <TextArea
              value={historyItemRaw}
              onChange={(e) => handleHistoryChange(e.target.value)}
              autoSize={{ minRows: 8, maxRows: 20 }}
              status={parseError ? "error" : undefined}
              style={{ fontFamily: "monospace", fontSize: 12 }}
            />
            {parseError && <div style={{ color: "#ff4d4f", fontSize: 12, marginTop: 4 }}>{parseError}</div>}
            {!parseError && (
              <div style={{ color: "#888", fontSize: 12, marginTop: 4 }}>
                {"格式：{ platform, shop, buyer, product, chatList: [...], detail }  —  shop 和 platform 字段自动用于路由到对应店铺"}
              </div>
            )}
          </div>

          <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={loading} size="large">
            发送并查看 Pipeline
          </Button>
        </Space>
      </Card>

      {loading && (
        <Card style={{ marginTop: 16, textAlign: "center" }}>
          <Spin size="large">
            <div style={{ padding: 32, color: "#888" }}>处理中，请稍候...</div>
          </Spin>
        </Card>
      )}

      {result && !loading && (
        <div style={{ marginTop: 16 }}>
          <Card size="small" title="消息解析" style={{ marginBottom: 12 }}>
            <Space wrap>
              <span><Text type="secondary">店铺：</Text><Text strong>{result.shop_name}</Text></span>
              <span><Text type="secondary">买家：</Text><Text strong>{result.extracted_buyer}</Text></span>
              <span><Text type="secondary">提取消息：</Text><Text code>{result.extracted_message}</Text></span>
              <span><Text type="secondary">历史轮次：</Text><Text>{result.history_turns_count}</Text></span>
              {result.product_name && result.product_name !== "无" && (
                <span><Text type="secondary">商品：</Text><Text>{result.product_name}</Text></span>
              )}
            </Space>
          </Card>

          <Card size="small" title="处理 Pipeline" style={{ marginBottom: 12 }}>
            <Space direction="vertical" style={{ width: "100%" }} size={8}>
              {result.steps.map((step, i) => (
                <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                  <div style={{ paddingTop: 14, color: "#999", fontSize: 12, minWidth: 20, textAlign: "center" }}>
                    {i + 1}
                  </div>
                  <div style={{ flex: 1 }}>
                    <StepCard step={step} />
                  </div>
                  {i < result.steps.length - 1 && (
                    <div style={{ paddingTop: 14, color: "#d9d9d9" }}>
                      <RightOutlined />
                    </div>
                  )}
                </div>
              ))}
            </Space>
          </Card>

          {result.final_reply !== undefined && (
            <Card
              title="最终回复"
              size="small"
              extra={
                <Space>
                  {result.final_source && (
                    <Tag color="blue">{SOURCE_LABELS[result.final_source] ?? result.final_source}</Tag>
                  )}
                  <Tag color={result.escalated ? "warning" : "success"}>
                    {result.escalated ? "转人工" : "自动回复"}
                  </Tag>
                  {result.confidence !== undefined && (
                    <Tag color={result.confidence >= (result.confidence_threshold ?? 85) ? "green" : "orange"}>
                      置信度 {result.confidence}
                      {result.confidence_threshold !== undefined ? ` / 阈值 ${result.confidence_threshold}` : ""}
                    </Tag>
                  )}
                  {result.total_elapsed_ms !== undefined && (
                    <Text type="secondary" style={{ fontSize: 12 }}>{result.total_elapsed_ms}ms</Text>
                  )}
                </Space>
              }
            >
              {result.final_reply ? (
                <div style={{ background: "#f6ffed", padding: 12, borderRadius: 4, whiteSpace: "pre-wrap" }}>
                  {result.final_reply}
                </div>
              ) : (
                <div style={{ color: "#888", fontStyle: "italic" }}>（无回复文本，已转人工处理）</div>
              )}
            </Card>
          )}

          {result.error && (
            <Card title="错误" size="small" style={{ borderColor: "#ff4d4f" }}>
              <Text type="danger">{result.error}</Text>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
