import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import { Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";
import { useCategories } from "../hooks/useCategories";

const { Title: ATitle } = Typography;

interface PhraseItem { id: number; shop_id: string; phrase: string; }
interface ShopOption { id: string; name: string; category_id: string; }

export default function DecoyPhrases() {
  const notify = useNotify();
  const [shops, setShops] = useState<ShopOption[]>([]);
  const [allShops, setAllShops] = useState<{ shop_id: string; name: string; category_id: string }[]>([]);
  const [categoryId, setCategoryId] = useState<string>("");
  const [shopId, setShopId] = useState<string>("");
  const [items, setItems] = useState<PhraseItem[]>([]);
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
    fetch(`${apiUrl}/decoy-phrases?${params}`)
      .then((r) => r.json())
      .then((data) => { setItems(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { notify("加载失败", { type: "error" }); setLoading(false); });
  };

  useEffect(() => { load(); }, [categoryId, shopId]); // eslint-disable-line

  const handleDelete = (id: number) => {
    Modal.confirm({
      title: "确认删除？",
      okText: "删除",
      okButtonProps: { danger: true },
      onOk: async () => {
        await fetch(`${apiUrl}/decoy-phrases/${id}`, { method: "DELETE" });
        setItems((prev) => prev.filter((i) => i.id !== id));
        notify("已删除", { type: "success" });
      },
    });
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const res = await fetch(`${apiUrl}/decoy-phrases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shop_id: shopId || "global", phrase: values.phrase }),
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
    { title: "话术内容", dataIndex: "phrase", key: "phrase" },
    {
      title: "店铺",
      key: "shop_id",
      render: (_: unknown, record: PhraseItem) => {
        const shop = allShops.find((s) => s.shop_id === record.shop_id);
        return shop ? shop.name : record.shop_id;
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 80,
      render: (_: unknown, record: PhraseItem) => (
        <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)} />
      ),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 800 }}>
      <Title title="搪塞话术" />
      <ATitle level={4} style={{ marginBottom: 24 }}>搪塞话术池管理</ATitle>

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
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加话术</Button>
        </Space>
      </Card>

      <Card
        title="搪塞话术池"
        extra={<Tag color="blue">转人工时随机选一条发送给买家</Tag>}
      >
        <Table dataSource={items} columns={columns} rowKey="id" size="small" loading={loading}
          locale={{ emptyText: "暂无话术，将使用内置默认话术" }} />
      </Card>

      <Modal open={modalOpen} onCancel={() => setModalOpen(false)} onOk={handleSave}
        okText="添加" cancelText="取消" confirmLoading={saving} title="添加搪塞话术" destroyOnHidden>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="phrase" label="话术内容" rules={[{ required: true, message: "请输入话术" }]}>
            <Input.TextArea autoSize={{ minRows: 2 }} placeholder="亲，稍等我查一下哈~" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
