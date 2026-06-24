import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import { Button, Card, Descriptions, Modal, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
import { EyeOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";

const { Title: ATitle, Text } = Typography;

interface ArchiveItem {
  id: number;
  shop_id: string;
  buyer_id: string;
  session_id: string | null;
  summary: string | null;
  full_history: string | null;
  resolution: string | null;
  created_at: string;
}

interface ShopOption { id: string; name: string; }

export default function ConversationArchives() {
  const notify = useNotify();
  const [shops, setShops] = useState<ShopOption[]>([]);
  const [shopId, setShopId] = useState<string>("");
  const [items, setItems] = useState<ArchiveItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<ArchiveItem | null>(null);

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
    fetch(`${apiUrl}/conversation-archives?shop_id=${shopId}`)
      .then((r) => r.json())
      .then((data) => { setItems(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { notify("加载失败", { type: "error" }); setLoading(false); });
  }, [shopId, notify]);

  const parseHistory = (json: string | null) => {
    if (!json) return [];
    try { return JSON.parse(json); } catch { return []; }
  };

  const columns = [
    { title: "时间", dataIndex: "created_at", key: "created_at", width: 160 },
    { title: "买家", dataIndex: "buyer_id", key: "buyer_id", width: 120 },
    {
      title: "摘要",
      dataIndex: "summary",
      key: "summary",
      render: (v: string | null) => <Tooltip title={v}><Text ellipsis style={{ maxWidth: 300, display: "block" }}>{v ?? "-"}</Text></Tooltip>,
    },
    {
      title: "处理结果",
      dataIndex: "resolution",
      key: "resolution",
      width: 120,
      render: (v: string | null) => v ? <Tag color={v === "resolved" ? "success" : "default"}>{v}</Tag> : "-",
    },
    {
      title: "操作",
      key: "actions",
      width: 80,
      render: (_: unknown, record: ArchiveItem) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => setDetail(record)}>详情</Button>
      ),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1100 }}>
      <Title title="对话归档" />
      <ATitle level={4} style={{ marginBottom: 24 }}>对话归档查询</ATitle>

      <Card style={{ marginBottom: 16 }}>
        <Space>
          <Select
            placeholder="选择店铺"
            style={{ minWidth: 200 }}
            value={shopId || undefined}
            onChange={setShopId}
            options={shops.map((s) => ({ value: s.id, label: s.name }))}
          />
        </Space>
      </Card>

      {!shopId ? (
        <Text type="secondary">请先选择店铺</Text>
      ) : (
        <Card>
          <Table dataSource={items} columns={columns} rowKey="id" size="small" loading={loading}
            pagination={{ pageSize: 50, showTotal: (t) => `共 ${t} 条` }} />
        </Card>
      )}

      <Modal
        open={!!detail}
        onCancel={() => setDetail(null)}
        footer={null}
        title={`对话详情 — ${detail?.buyer_id}`}
        width={700}
      >
        {detail && (
          <>
            <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="买家">{detail.buyer_id}</Descriptions.Item>
              <Descriptions.Item label="时间">{detail.created_at}</Descriptions.Item>
              <Descriptions.Item label="处理结果">{detail.resolution ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="会话 ID">{detail.session_id ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="摘要" span={2}>{detail.summary ?? "-"}</Descriptions.Item>
            </Descriptions>

            <ATitle level={5}>对话历史</ATitle>
            {parseHistory(detail.full_history).length > 0 ? (
              parseHistory(detail.full_history).map((turn: { role: string; content: string }, i: number) => (
                <div key={i} style={{
                  background: turn.role === "user" ? "#f5f5f5" : "#e6f4ff",
                  padding: "8px 12px",
                  borderRadius: 6,
                  marginBottom: 8,
                }}>
                  <Tag color={turn.role === "user" ? "default" : "blue"}>{turn.role}</Tag>
                  <span style={{ marginLeft: 8 }}>{turn.content}</span>
                </div>
              ))
            ) : (
              <Text type="secondary">无历史记录</Text>
            )}
          </>
        )}
      </Modal>
    </div>
  );
}
