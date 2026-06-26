import { useEffect, useState } from "react";
import { Title } from "react-admin";
import {
  Button,
  Card,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { apiUrl } from "../dataProvider";
import { useCategories, getCategoryNameById } from "../hooks/useCategories";
import ShopCreate from "./ShopCreate";

const { Title: ATitle, Text } = Typography;

interface ShopItem {
  shop_id: string;
  category_id: string;
  platform: string;
  name: string;
  obsidian_vault: string;
  api_key: string;
  confidence_threshold: number;
  enabled: boolean;
  created_at: string;
}

const PLATFORMS: Record<string, string> = {
  taobao: "千牛（淘宝）",
  pinduoduo: "拼多多",
  jd: "京东",
  douyin: "抖店",
};

export default function ShopList() {
  const [shops, setShops] = useState<ShopItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterCategory, setFilterCategory] = useState<string>("");
  const [deleteModal, setDeleteModal] = useState<{ open: boolean; shopId: string }>({ open: false, shopId: "" });
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const { categories, loading: catLoading, reload: reloadCategories } = useCategories();

  const loadShops = () => {
    setLoading(true);
    fetch(`${apiUrl}/shops`)
      .then((r) => r.json())
      .then((data: ShopItem[]) => {
        setShops(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => { setLoading(false); });
  };

  useEffect(() => { loadShops(); }, []);

  const filtered = shops.filter((s) => {
    if (filterCategory && s.category_id !== filterCategory) return false;
    return true;
  });

  const handleToggle = async (shop: ShopItem) => {
    await fetch(`${apiUrl}/shops/${encodeURIComponent(shop.shop_id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !shop.enabled }),
    });
    loadShops();
  };

  const handleDelete = async () => {
    const res = await fetch(`${apiUrl}/shops/${encodeURIComponent(deleteModal.shopId)}`, { method: "DELETE" });
    if (res.ok || res.status === 204) {
      message.success("已删除");
      loadShops();
    } else {
      const err = await res.json().catch(() => ({}));
      message.error((err as { detail?: string }).detail || "删除失败");
    }
    setDeleteModal({ open: false, shopId: "" });
  };

  const columns = [
    {
      title: "店铺 ID",
      dataIndex: "shop_id",
      key: "shop_id",
      width: 160,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: "分类",
      dataIndex: "category_id",
      key: "category_id",
      width: 100,
      render: (v: string) => (
        <Text type="secondary">{getCategoryNameById(categories, v)}</Text>
      ),
    },
    {
      title: "平台",
      dataIndex: "platform",
      key: "platform",
      width: 100,
      render: (v: string) => PLATFORMS[v] || v,
    },
    {
      title: "店铺名称",
      dataIndex: "name",
      key: "name",
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: "置信度阈值",
      dataIndex: "confidence_threshold",
      key: "confidence_threshold",
      width: 100,
      render: (v: number) => <Text type="secondary">{v}%</Text>,
    },
    {
      title: "启用",
      dataIndex: "enabled",
      key: "enabled",
      width: 70,
      render: (enabled: boolean, record: ShopItem) => (
        <Switch size="small" checked={enabled} onChange={() => handleToggle(record)} />
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 100,
      render: (_: unknown, record: ShopItem) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => window.location.hash = `#/shops/${record.shop_id}/edit`}
          />
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => setDeleteModal({ open: true, shopId: record.shop_id })}
          />
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1100 }}>
      <Title title="店铺管理" />
      <ATitle level={4} style={{ marginBottom: 24 }}>店铺列表</ATitle>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Text type="secondary">分类：</Text>
          <Select
            placeholder="请选择分类查看"
            style={{ minWidth: 180 }}
            value={filterCategory || undefined}
            onChange={(v) => setFilterCategory(v ?? "")}
            allowClear
            loading={catLoading}
            options={categories.filter((c) => c.id !== "default").map((c) => ({ value: c.id, label: c.name }))}
          />
          <div style={{ flex: 1 }} />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateModalOpen(true)}
          >
            新增店铺
          </Button>
        </Space>
      </Card>

      <Card>
        {shops.length === 0 && !loading ? (
          <Text type="secondary">暂无店铺，点击「新增店铺」添加</Text>
        ) : (
          <Table
            dataSource={filterCategory ? filtered : shops}
            columns={columns}
            rowKey="shop_id"
            size="small"
            loading={loading}
            pagination={{ pageSize: 20, showSizeChanger: true }}
            locale={{ emptyText: "该分类下暂无店铺" }}
          />
        )}
      </Card>

      <Modal
        title="确认删除"
        open={deleteModal.open}
        onCancel={() => setDeleteModal({ open: false, shopId: "" })}
        onOk={handleDelete}
        okText="删除"
        okButtonProps={{ danger: true }}
        cancelText="取消"
      >
        <Text>确认删除店铺 <Tag>{deleteModal.shopId}</Tag>？此操作不可恢复。</Text>
      </Modal>

      <ShopCreate
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        defaultCategory={filterCategory}
        onCreated={() => { loadShops(); reloadCategories(); }}
      />
    </div>
  );
}
