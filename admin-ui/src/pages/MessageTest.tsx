import { useState } from "react";
import { Title, useNotify } from "react-admin";
import { Button, Card, Collapse, Input, Space, Tag, Typography, Spin } from "antd";
import { SendOutlined, CheckCircleOutlined, CloseCircleOutlined, RightOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";

const { TextArea } = Input;
const { Text } = Typography;

const DEFAULT_HISTORY_ITEM = JSON.stringify({
  "platform": "抖音",
  "shop": "抖音艾睿斯旗舰店",
  "kefu": "清博照明运营",
  "buyer": "芬达",
  "product": "无",
  "last_interaction_at": "2026-06-28T16:30:00+08:00",
  "chatList": [
      "6月14日16: 21\n用户超时未回复，系统关闭会话",
      "6月17日13: 10\n机器人接待中",
      "订单号6953495324704314513\n已完成\n客厅吸顶灯2026新款超薄LED现代简约大气房间卧室大厅灯中山灯具\n共1件，总价¥67.00\n代客发起售后\n发售后卡\n发物流卡\n邀评\n6月17日13: 10: 44",
      "发哪里去了\n6月17日13: 10: 50",
      "智能客服\n看到订单啦～您说“发哪里”是灯条没找到、安装材料没收到，还是刚才说按原地址寄出的主灯呀，帮您核对物流细节～\n6月17日13: 10: 57\n已读\n抖音电商智能客服发送",
      "灯条\n6月17日13: 11: 09",
      "转人工\n6月17日13: 11: 11",
  ],
  "detail": "全部\n未完结\n售后中\n已完结\n已关闭\n已完成\n咨询中\n+0\n6953495324704314513\n补发(3486736)#\n客厅吸顶灯2026新款超薄LED现代简约大气房间卧室大厅灯中山灯具\n[已发1/1]\n运费险\n7天\n极速退\n小店自卖\n商品卡\n+2\n规格\n方60x60三色变光60瓦\n编码\nS黑双金线60*60三色144w\n代客发起售后\n发售后卡\n实付金额\n¥\n67.\n00\n(含运费¥0.00)\n优惠¥1.00\n付款时间\n2026/06/0808: 52: 40(微信)\n物流信息\n申通快递770325078690022\n[已签收]2026-06-1016: 49: 40\n收货信息\n卞*，1***\n，山东省烟台市莱州市沙河镇***\n发货时间\n2026-06-0812: 50\n发物流卡\n打款\n自助开票\n邀评\n已加载近6个月订单，点击\n查询近3年订单"
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
  reply: string;
  escalated: boolean;
  shop_id?: string;
  shop_name?: string;
  extracted_buyer?: string;
  extracted_message?: string;
  history_turns_count?: number;
  product_name?: string;
  steps?: StepInfo[];
  final_source?: string;
  final_reply?: string;
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
          <div><Text type="secondary">意图：</Text><Tag color="blue">{step.intent || "未识别"}</Tag></div>
          {step.entities && step.entities.length > 0 && (
            <div><Text type="secondary">实体：</Text>{step.entities.map((e, i) => <Tag key={i}>{e}</Tag>)}</div>
          )}
          {step.rewrite_query && (
            <div><Text type="secondary">改写查询：</Text><Text code>{step.rewrite_query}</Text></div>
          )}
        </div>
      )}

      {step.step === "intent" && hasError && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div><Text type="secondary">意图：</Text><Tag color="error">{step.intent || "未识别"}</Tag></div>
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
            <Text strong>{step.chunks_count ?? 0}</Text>
            <Text type="secondary"> 条知识片段</Text>
            {step.chunks_count === 0 && (
              <Tag color="warning" style={{ marginLeft: 8 }}>未命中（向量库无相关知识）</Tag>
            )}
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
    const parsed = validateHistoryItem(historyItemRaw);
    if (!parsed) {
      notify("请输入合法的 JSON 对象，需包含 chatList 字段", { type: "warning" });
      return;
    }

    if (!parsed.shop) {
      notify("缺少 shop 字段", { type: "warning" });
      return;
    }

    setLoading(true);
    setResult(null);

    try {
      const res = await fetch(`${apiUrl}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed),
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
            发送（触发完整处理流程，含转人工）
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
          {(result.shop_name || result.extracted_buyer) && (
            <Card size="small" title="消息解析" style={{ marginBottom: 12 }}>
              <Space wrap>
                {result.shop_name && <span><Text type="secondary">店铺：</Text><Text strong>{result.shop_name}</Text></span>}
                {result.extracted_buyer && <span><Text type="secondary">买家：</Text><Text strong>{result.extracted_buyer}</Text></span>}
                {result.extracted_message && <span><Text type="secondary">提取消息：</Text><Text code>{result.extracted_message}</Text></span>}
                {result.history_turns_count !== undefined && <span><Text type="secondary">历史轮次：</Text><Text>{result.history_turns_count}</Text></span>}
                {result.product_name && result.product_name !== "无" && (
                  <span><Text type="secondary">商品：</Text><Text>{result.product_name}</Text></span>
                )}
              </Space>
            </Card>
          )}

          {result.steps && (
            <Card size="small" title="处理 Pipeline" style={{ marginBottom: 12 }}>
              <Space direction="vertical" style={{ width: "100%" }} size={8}>
                {result.steps && result.steps.map((step, i) => (
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
          )}

          {(result.final_reply !== undefined || result.reply) && (
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
              {result.final_reply ?? result.reply ? (
                <div style={{ background: "#f6ffed", padding: 12, borderRadius: 4, whiteSpace: "pre-wrap" }}>
                  {result.final_reply ?? result.reply}
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
