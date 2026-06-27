import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import { Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";
import { useCategories } from "../hooks/useCategories";

const { Title: ATitle } = Typography;

interface KeywordItem { id: number; shop_id: string; keyword: string; }
interface ShopOption { id: string; name: string; category_id: string; }

export default function EscalationKeywords() {
  const notify = useNotify();
  const [shops, setShops] = useState<ShopOption[]>([]);
  const [allShops, setAllShops] = useState<{ shop_id: string; name: string; category_id: string }[]>([]);
  const [categoryId, setCategoryId] = useState<string>("");
  const [shopId, setShopId] = useState<string>("");
  const [items, setItems] = useState<KeywordItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const { categories, loading: catLoading } = useCategories();

  useEffect(() => {
    fetch(`${apiUrl}/shops`)
      .then((r) => r.json())
      .then((data: { shop_id: string; name: string; category_id: string }[]) => {
        if (Array.isArray(data)) setAllShops(data);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!catLoading && categories.length > 0 && !categoryId) {
      const firstCat = categories.find((c) => c.id !== "default");
      if (firstCat) {
        setCategoryId(firstCat.id);
      }
    }
  }, [categories, catLoading]);

  useEffect(() => {
    setShops(categoryId ? allShops.filter((s) => s.category_id === categoryId) : []);
  }, [categoryId, allShops]);

  const load = () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (categoryId) params.set("category_id", categoryId);
    if (shopId) params.set("shop_id", shopId);
    fetch(`${apiUrl}/escalation-keywords?${params}`)
      .then((r) => r.json())
      .then((data) => { setItems(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { notify("加载失败", { type: "error" }); setLoading(false); });
  };

  useEffect(() => { load(); }, [categoryId, shopId]); // eslint-disable-line

  const handleDelete = (id: number) => {
    Modal.confirm({
      title: "确认删除该关键词？",
      okText: "删除",
      okButtonProps: { danger: true },
      onOk: async () => {
        await fetch(`${apiUrl}/escalation-keywords/${id}`, { method: "DELETE" });
        setItems((prev) => prev.filter((i) => i.id !== id));
        notify("已删除", { type: "success" });
      },
    });
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const res = await fetch(`${apiUrl}/escalation-keywords`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shop_id: shopId || "global", keyword: values.keyword }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "保存失败"); }
      notify("已添加", { type: "success" });
      setModalOpen(false);
      form.resetFields();
      load();
    } catch (e: unknown) {
      notify(e instanceof Error ? e.message : "保存失败", { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    {
      title: "关键词",
      dataIndex: "keyword",
      key: "keyword",
      render: (v: string) => <Tag color="red">{v}</Tag>,
    },
    {
      title: "店铺",
      key: "shop_id",
      render: (_: unknown, record: KeywordItem) => {
        const shop = allShops.find((s) => s.shop_id === record.shop_id);
        return shop ? shop.name : record.shop_id;
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 80,
      render: (_: unknown, record: KeywordItem) => (
        <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)} />
      ),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 800 }}>
      <Title title="告警关键词" />
      <ATitle level={4} style={{ marginBottom: 24 }}>硬转人工关键词管理</ATitle>

      <Card style={{ marginBottom: 16 }}>
        <Space>
          <Select
            placeholder="选择分类"
            style={{ minWidth: 180 }}
            value={categoryId || undefined}
            onChange={(v) => {
              setCategoryId(v ?? "");
              setShopId("");
              setShops(v ? allShops.filter((s) => s.category_id === v) : []);
            }}
            allowClear
            options={categories.filter((c) => c.id !== "default").map((c) => ({ value: c.id, label: c.name }))}
          />
          <Select value={shopId || undefined} onChange={(v) => setShopId(v ?? "")} style={{ minWidth: 200 }} allowClear
            placeholder="全部店铺" options={shops.map((s) => ({ value: s.shop_id, label: s.name }))} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加关键词</Button>
        </Space>
      </Card>

      <Card extra={<Tag color="warning">命中即转人工，不经 LLM</Tag>}>
        <Table dataSource={items} columns={columns} rowKey="id" size="small" loading={loading}
          locale={{ emptyText: "暂无关键词，点击「添加关键词」配置" }} />
      </Card>

      <Modal open={modalOpen} onCancel={() => setModalOpen(false)} onOk={handleSave}
        okText="添加" cancelText="取消" confirmLoading={saving} title="添加转人工关键词" destroyOnHidden>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="keyword" label="关键词" rules={[{ required: true, message: "请输入关键词" }]}>
            <Input placeholder="如：投诉、假货、12315" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
