import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { PlusOutlined, DeleteOutlined, EditOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";

const { Title: ATitle, Text } = Typography;

interface KnowledgeItem {
  id: number;
  shop_id: string;
  category: string;
  code: string;
  title: string;
  content: string;
  status: number;
  qdrant_sync: number;
  created_at: string;
  updated_at: string;
}

interface ShopOption { id: string; name: string; }

const CATEGORIES = [
  { value: "shortcut", label: "快捷短语" },
  { value: "policy", label: "政策说明" },
  { value: "tutorial", label: "使用教程" },
  { value: "faq_supplement", label: "FAQ 补充" },
];

const STATUS_MAP: Record<number, { label: string; color: string }> = {
  1: { label: "已发布", color: "success" },
  0: { label: "草稿", color: "default" },
  [-1]: { label: "已删除", color: "error" },
};

export default function KnowledgeManage() {
  const notify = useNotify();
  const [shops, setShops] = useState<ShopOption[]>([]);
  const [shopId, setShopId] = useState<string>("global");
  const [filterCategory, setFilterCategory] = useState<string>("");
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`${apiUrl}/shops`)
      .then((r) => r.json())
      .then((data: { shop_id: string; name: string }[]) =>
        setShops([{ id: "global", name: "全局（global）" }, ...data.map((s) => ({ id: s.shop_id, name: s.name }))])
      )
      .catch(() => {});
  }, []);

  const load = () => {
    setLoading(true);
    const p = new URLSearchParams({ shop_id: shopId });
    if (filterCategory) p.set("category", filterCategory);
    fetch(`${apiUrl}/knowledge?${p}`)
      .then((r) => r.json())
      .then((data) => { setItems(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { notify("加载失败", { type: "error" }); setLoading(false); });
  };

  useEffect(() => { load(); }, [shopId, filterCategory]); // eslint-disable-line

  const openCreate = () => {
    setEditingId(null);
    form.resetFields();
    form.setFieldsValue({ shop_id: shopId, category: "shortcut" });
    setModalOpen(true);
  };

  const openEdit = (item: KnowledgeItem) => {
    setEditingId(item.id);
    form.setFieldsValue({ code: item.code, title: item.title, content: item.content, category: item.category });
    setModalOpen(true);
  };

  const handleDelete = (id: number) => {
    Modal.confirm({
      title: "确认删除？",
      okText: "删除",
      okButtonProps: { danger: true },
      onOk: async () => {
        await fetch(`${apiUrl}/knowledge/${id}`, { method: "DELETE" });
        setItems((prev) => prev.filter((i) => i.id !== id));
        notify("已删除", { type: "success" });
      },
    });
  };

  const handleToggleStatus = async (item: KnowledgeItem) => {
    const newStatus = item.status === 1 ? 0 : 1;
    const res = await fetch(`${apiUrl}/knowledge/${item.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus }),
    });
    if (res.ok) {
      setItems((prev) => prev.map((i) => i.id === item.id ? { ...i, status: newStatus } : i));
    } else {
      notify("操作失败", { type: "error" });
    }
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const res = editingId
        ? await fetch(`${apiUrl}/knowledge/${editingId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code: values.code, title: values.title, content: values.content }),
          })
        : await fetch(`${apiUrl}/knowledge`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ shop_id: shopId, category: values.category, code: values.code ?? "", title: values.title ?? "", content: values.content }),
          });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "保存失败"); }
      notify(editingId ? "已更新" : "已创建", { type: "success" });
      setModalOpen(false);
      load();
    } catch (e: unknown) {
      notify(e instanceof Error ? e.message : "保存失败", { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    {
      title: "发布",
      key: "status",
      width: 60,
      render: (_: unknown, record: KnowledgeItem) => (
        <Switch size="small" checked={record.status === 1} onChange={() => handleToggleStatus(record)} />
      ),
    },
    {
      title: "分类",
      dataIndex: "category",
      key: "category",
      width: 100,
      render: (v: string) => <Tag>{CATEGORIES.find((c) => c.value === v)?.label ?? v}</Tag>,
    },
    { title: "Code", dataIndex: "code", key: "code", width: 120 },
    { title: "标题", dataIndex: "title", key: "title", width: 160 },
    {
      title: "内容",
      dataIndex: "content",
      key: "content",
      render: (v: string) => <Tooltip title={v}><Text ellipsis style={{ maxWidth: 300, display: "block" }}>{v}</Text></Tooltip>,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status_label",
      width: 80,
      render: (v: number) => <Tag color={STATUS_MAP[v]?.color}>{STATUS_MAP[v]?.label ?? v}</Tag>,
    },
    { title: "更新时间", dataIndex: "updated_at", key: "updated_at", width: 160 },
    {
      title: "操作",
      key: "actions",
      width: 100,
      render: (_: unknown, record: KnowledgeItem) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)} />
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1100 }}>
      <Title title="知识库管理" />
      <ATitle level={4} style={{ marginBottom: 24 }}>知识条目管理</ATitle>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select value={shopId} onChange={setShopId} style={{ minWidth: 200 }}
            options={shops.map((s) => ({ value: s.id, label: s.name }))} />
          <Select placeholder="分类筛选" allowClear style={{ minWidth: 150 }}
            value={filterCategory || undefined} onChange={(v) => setFilterCategory(v ?? "")}
            options={CATEGORIES} />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增条目</Button>
        </Space>
      </Card>

      <Card>
        <Table dataSource={items} columns={columns} rowKey="id" size="small" loading={loading} />
      </Card>

      <Modal open={modalOpen} onCancel={() => setModalOpen(false)} onOk={handleSave}
        okText="保存" cancelText="取消" confirmLoading={saving}
        title={editingId ? "编辑知识条目" : "新增知识条目"} width={600} destroyOnClose>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          {!editingId && (
            <Form.Item name="category" label="分类" rules={[{ required: true }]}>
              <Select options={CATEGORIES} />
            </Form.Item>
          )}
          <Form.Item name="code" label="Code 标签" extra="快捷短语唯一标识符，如 delivery_time">
            <Input placeholder="delivery_time" />
          </Form.Item>
          <Form.Item name="title" label="标题">
            <Input placeholder="发货时间说明" />
          </Form.Item>
          <Form.Item name="content" label="内容" rules={[{ required: true, message: "请输入内容" }]}>
            <Input.TextArea autoSize={{ minRows: 4 }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
