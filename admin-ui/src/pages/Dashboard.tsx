import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import { Card, Col, Row, Statistic, Table, Tag, Typography, Spin } from "antd";
import {
  RiseOutlined,
  CustomerServiceOutlined,
  RobotOutlined,
  ShopOutlined,
} from "@ant-design/icons";
import { apiUrl } from "../dataProvider";

const { Title: ATitle } = Typography;

interface Stat {
  shop_id: string;
  stat_date: string;
  total_sessions: number;
  faq_hits: number;
  llm_calls: number;
  escalations: number;
  faq_hit_rate: number;
}

const columns = [
  { title: "店铺 ID", dataIndex: "shop_id", key: "shop_id",
    render: (v: string) => <Tag>{v}</Tag> },
  { title: "会话数", dataIndex: "total_sessions", key: "total_sessions", align: "right" as const },
  { title: "FAQ 命中", dataIndex: "faq_hits", key: "faq_hits", align: "right" as const },
  {
    title: "FAQ 命中率", dataIndex: "faq_hit_rate", key: "faq_hit_rate", align: "right" as const,
    render: (v: number) => (
      <Tag color={v >= 0.8 ? "success" : "warning"}>{(v * 100).toFixed(1)}%</Tag>
    ),
  },
  { title: "LLM 调用", dataIndex: "llm_calls", key: "llm_calls", align: "right" as const },
  {
    title: "转人工", dataIndex: "escalations", key: "escalations", align: "right" as const,
    render: (v: number) => v > 0 ? <Tag color="error">{v}</Tag> : v,
  },
];

export default function Dashboard() {
  const [stats, setStats] = useState<Stat[]>([]);
  const [loading, setLoading] = useState(true);
  const notify = useNotify();
  const today = new Date().toISOString().split("T")[0];

  useEffect(() => {
    fetch(`${apiUrl}/dashboard?date=${today}`)
      .then((r) => r.json())
      .then((data) => { setStats(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { notify("加载统计数据失败", { type: "error" }); setLoading(false); });
  }, [today, notify]);

  const totals = stats.reduce(
    (acc, s) => ({
      sessions: acc.sessions + s.total_sessions,
      faq: acc.faq + s.faq_hits,
      llm: acc.llm + s.llm_calls,
      escalations: acc.escalations + s.escalations,
    }),
    { sessions: 0, faq: 0, llm: 0, escalations: 0 }
  );

  return (
    <div style={{ padding: 24 }}>
      <Title title="仪表盘" />
      <ATitle level={4} style={{ marginBottom: 24 }}>今日概览 · {today}</ATitle>

      {loading ? (
        <div style={{ display: "flex", justifyContent: "center", marginTop: 48 }}>
          <Spin size="large" />
        </div>
      ) : (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
            <Col xs={24} sm={12} md={6}>
              <Card>
                <Statistic title="总会话数" value={totals.sessions} prefix={<RiseOutlined style={{ color: "#1677ff" }} />} />
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card>
                <Statistic title="FAQ 命中" value={totals.faq} prefix={<RobotOutlined style={{ color: "#52c41a" }} />} />
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card>
                <Statistic title="LLM 调用" value={totals.llm} prefix={<CustomerServiceOutlined style={{ color: "#fa8c16" }} />} />
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card>
                <Statistic title="转人工" value={totals.escalations} prefix={<ShopOutlined style={{ color: "#ff4d4f" }} />} valueStyle={{ color: totals.escalations > 0 ? "#ff4d4f" : undefined }} />
              </Card>
            </Col>
          </Row>

          <Card title="各店铺详情">
            <Table
              dataSource={stats}
              columns={columns}
              rowKey="shop_id"
              size="small"
              pagination={false}
              locale={{ emptyText: "今日暂无会话数据" }}
            />
          </Card>
        </>
      )}
    </div>
  );
}
