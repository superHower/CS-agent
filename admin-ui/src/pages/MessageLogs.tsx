import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import { Card, DatePicker, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
import dayjs from "dayjs";
import { apiUrl } from "../dataProvider";

const { Title: ATitle, Text } = Typography;

interface LogItem {
  id: number;
  shop_id: string | null;
  buyer_id: string | null;
  message_id: string | null;
  user_msg: string | null;
  match_source: string | null;
  reply: string | null;
  confidence: number | null;
  elapsed_ms: number | null;
  llm_tokens_in: number | null;
  llm_tokens_out: number | null;
  is_escalated: boolean;
  created_at: string;
}

interface ShopOption { id: string; name: string; }

const SOURCE_COLOR: Record<string, string> = {
  faq_cache: "green",
  faq_match: "cyan",
  llm: "blue",
  escalated: "red",
};

export default function MessageLogs() {
  const notify = useNotify();
  const [shops, setShops] = useState<ShopOption[]>([]);
  const [shopId, setShopId] = useState<string>("");
  const [date, setDate] = useState<string>(new Date().toISOString().split("T")[0]);
  const [items, setItems] = useState<LogItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`${apiUrl}/shops`)
      .then((r) => r.json())
      .then((data: { shop_id: string; name: string }[]) =>
        setShops(data.map((s) => ({ id: s.shop_id, name: s.name })))
      )
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!shopId) return;
    setLoading(true);
    const p = new URLSearchParams({ shop_id: shopId, date });
    fetch(`${apiUrl}/message-logs?${p}`)
      .then((r) => r.json())
      .then((data) => { setItems(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { notify("加载失败", { type: "error" }); setLoading(false); });
  }, [shopId, date, notify]);

  const columns = [
    { title: "时间", dataIndex: "created_at", key: "created_at", width: 160 },
    { title: "买家", dataIndex: "buyer_id", key: "buyer_id", width: 120 },
    {
      title: "消息",
      dataIndex: "user_msg",
      key: "user_msg",
      render: (v: string | null) => <Tooltip title={v}><Text ellipsis style={{ maxWidth: 200, display: "block" }}>{v ?? "-"}</Text></Tooltip>,
    },
    {
      title: "来源",
      dataIndex: "match_source",
      key: "match_source",
      width: 100,
      render: (v: string | null) => v ? <Tag color={SOURCE_COLOR[v] ?? "default"}>{v}</Tag> : "-",
    },
    {
      title: "回复",
      dataIndex: "reply",
      key: "reply",
      render: (v: string | null) => <Tooltip title={v}><Text ellipsis style={{ maxWidth: 200, display: "block" }}>{v ?? "-"}</Text></Tooltip>,
    },
    {
      title: "置信度",
      dataIndex: "confidence",
      key: "confidence",
      width: 80,
      render: (v: number | null) => v !== null ? `${v}%` : "-",
    },
    { title: "耗时(ms)", dataIndex: "elapsed_ms", key: "elapsed_ms", width: 90 },
    {
      title: "转人工",
      dataIndex: "is_escalated",
      key: "is_escalated",
      width: 80,
      render: (v: boolean) => v ? <Tag color="warning">是</Tag> : <Tag>否</Tag>,
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1200 }}>
      <Title title="消息日志" />
      <ATitle level={4} style={{ marginBottom: 24 }}>消息处理日志</ATitle>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder="选择店铺"
            style={{ minWidth: 200 }}
            value={shopId || undefined}
            onChange={setShopId}
            options={shops.map((s) => ({ value: s.id, label: s.name }))}
          />
          <DatePicker
            value={dayjs(date)}
            onChange={(d) => d && setDate(d.format("YYYY-MM-DD"))}
            allowClear={false}
          />
        </Space>
      </Card>

      {!shopId ? (
        <Text type="secondary">请先选择店铺</Text>
      ) : (
        <Card>
          <Table
            dataSource={items}
            columns={columns}
            rowKey="id"
            size="small"
            loading={loading}
            scroll={{ x: 1100 }}
            pagination={{ pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
          />
        </Card>
      )}
    </div>
  );
}
