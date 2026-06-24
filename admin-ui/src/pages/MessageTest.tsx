import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import { AutoComplete, Button, Card, Input, Select, Space, Tag } from "antd";
import { SendOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";

const { TextArea } = Input;

const PLATFORMS = ["taobao", "pinduoduo", "jd", "douyin"];

interface RpaResponse {
  reply: string;
  escalated: boolean;
}

export default function MessageTest() {
  const notify = useNotify();
  const [shopNames, setShopNames] = useState<string[]>([]);
  const [shopName, setShopName] = useState<string>("");
  const [platform, setPlatform] = useState("taobao");
  const [buyerId, setBuyerId] = useState("");
  const [contentRaw, setContentRaw] = useState('["你好", "这个产品有货吗"]');
  const [contentError, setContentError] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RpaResponse | null>(null);
  const [reqBody, setReqBody] = useState<string>("");

  useEffect(() => {
    fetch(`${apiUrl}/shop-names`)
      .then((r) => r.json())
      .then((data: string[]) => setShopNames(data))
      .catch(() => {});
  }, []);

  const validateContent = (val: string): string[] | null => {
    try {
      const parsed = JSON.parse(val);
      if (!Array.isArray(parsed)) return null;
      if (!parsed.every((x) => typeof x === "string")) return null;
      return parsed;
    } catch {
      return null;
    }
  };

  const handleContentChange = (val: string) => {
    setContentRaw(val);
    const parsed = validateContent(val);
    setContentError(parsed === null ? '请输入合法的字符串数组，如 ["你好", "有货吗"]' : "");
  };

  const handleSend = async () => {
    const content = validateContent(contentRaw);
    if (!content) { setContentError("请输入合法的字符串数组"); return; }
    if (!shopName.trim()) { notify("请输入或选择店铺名称", { type: "warning" }); return; }
    if (!buyerId.trim()) { notify("请输入买家名称", { type: "warning" }); return; }

    setLoading(true);
    setResult(null);

    try {
      const resolveRes = await fetch(
        `${apiUrl}/shops/resolve-name?name=${encodeURIComponent(shopName.trim())}&platform=${platform}`
      );
      if (!resolveRes.ok) { notify("店铺解析失败", { type: "error" }); return; }
      const shop = await resolveRes.json();
      const shopId: string = shop.shop_id;

      fetch(`${apiUrl}/shop-names`).then((r) => r.json()).then(setShopNames).catch(() => {});

      const body = { shop_id: shopId, buyer_id: buyerId.trim(), content, platform };
      setReqBody(JSON.stringify({ ...body, _shop_name: shopName.trim() }, null, 2));

      const res = await fetch(`${apiUrl}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        notify(`请求失败: ${data.detail ?? res.statusText}`, { type: "error" });
      } else {
        setResult(data as RpaResponse);
      }
    } catch (e) {
      notify(`网络错误: ${e}`, { type: "error" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 800 }}>
      <Title title="消息测试" />
      <Card title="发送测试消息" extra="模拟影刀 RPA 推送消息到 POST /api/message">
        <Space direction="vertical" style={{ width: "100%" }} size={16}>
          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>平台</div>
            <Select
              value={platform}
              onChange={setPlatform}
              style={{ width: "100%" }}
              options={PLATFORMS.map((p) => ({ value: p, label: p }))}
            />
          </div>

          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>店铺名称</div>
            <AutoComplete
              value={shopName}
              options={shopNames.map((n) => ({ value: n }))}
              onChange={setShopName}
              style={{ width: "100%" }}
              placeholder="已有店铺可下拉选择；输入新名称会自动创建店铺"
            />
          </div>

          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>买家名称</div>
            <Input
              value={buyerId}
              onChange={(e) => setBuyerId(e.target.value)}
              placeholder="仅用于会话隔离，不写数据库"
            />
          </div>

          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>消息内容（字符串数组 JSON）</div>
            <TextArea
              value={contentRaw}
              onChange={(e) => handleContentChange(e.target.value)}
              autoSize={{ minRows: 3 }}
              status={contentError ? "error" : undefined}
            />
            {contentError && <div style={{ color: "#ff4d4f", fontSize: 12, marginTop: 4 }}>{contentError}</div>}
            {!contentError && <div style={{ color: "#888", fontSize: 12, marginTop: 4 }}>{'每个气泡一个字符串，如 ["你好", "有货吗"]'}</div>}
          </div>

          <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={loading}>
            发送
          </Button>
        </Space>
      </Card>

      {reqBody && (
        <Card title="请求体" size="small" style={{ marginTop: 16 }}>
          <pre style={{ background: "#f5f5f5", padding: 12, borderRadius: 4, fontSize: 12, overflow: "auto", margin: 0 }}>
            {reqBody}
          </pre>
        </Card>
      )}

      {result && (
        <Card
          title="响应结果"
          size="small"
          style={{ marginTop: 16 }}
          extra={<Tag color={result.escalated ? "warning" : "success"}>{result.escalated ? "已转人工" : "自动回复"}</Tag>}
        >
          {result.reply ? (
            <div style={{ background: "#f6ffed", padding: 12, borderRadius: 4, whiteSpace: "pre-wrap", marginBottom: 12 }}>
              {result.reply}
            </div>
          ) : (
            <div style={{ color: "#888", fontStyle: "italic", marginBottom: 12 }}>（无回复文本，已转人工处理）</div>
          )}
          <pre style={{ background: "#f5f5f5", padding: 12, borderRadius: 4, fontSize: 12, overflow: "auto", margin: 0 }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}
