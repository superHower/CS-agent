import { useEffect, useState, useRef } from "react";
import { Title, useNotify } from "react-admin";
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  UploadOutlined,
  DownloadOutlined,
} from "@ant-design/icons";
import { apiUrl } from "../dataProvider";

const { Title: ATitle, Text } = Typography;

interface ProductItem {
  id: number;
  shop_id: string;
  model: string;
  attributes: string;
  tags: string;
  qdrant_sync: number;
  created_at: string;
  updated_at: string;
}

interface ShopOption { id: string; name: string; }

const SYNC_MAP: Record<number, { label: string; color: string }> = {
  1: { label: "已同步", color: "success" },
  0: { label: "待同步", color: "default" },
  [-1]: { label: "同步失败", color: "error" },
};

export default function ProductManage() {
  const notify = useNotify();
  const [shops, setShops] = useState<ShopOption[]>([]);
  const [shopId, setShopId] = useState<string>("global");
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    fetch(`${apiUrl}/shops`)
      .then((r) => r.json())
      .then((data: { shop_id: string; name: string }[]) =>
        setShops([{ id: "global", name: "全局（global）" }, ...data.map((s) => ({ id: s.shop_id, name: s.name }))])
      )
      .catch(() => {});
  }, []);

  const loadProducts = () => {
    setLoading(true);
    fetch(`${apiUrl}/products?shop_id=${shopId}`)
      .then((r) => r.json())
      .then((data) => { setProducts(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { notify("加载产品列表失败", { type: "error" }); setLoading(false); });
  };

  useEffect(() => { loadProducts(); }, [shopId]); // eslint-disable-line

  const openCreate = () => {
    setEditingId(null);
    form.resetFields();
    form.setFieldValue("shop_id", shopId);
    setModalOpen(true);
  };

  const openEdit = (item: ProductItem) => {
    setEditingId(item.id);
    form.setFieldsValue({ attributes: item.attributes, tags: item.tags });
    setModalOpen(true);
  };

  const handleDelete = (id: number) => {
    Modal.confirm({
      title: "确认删除该产品？",
      okText: "删除",
      okButtonProps: { danger: true },
      onOk: async () => {
        const res = await fetch(`${apiUrl}/products/${id}`, { method: "DELETE" });
        if (res.ok || res.status === 204) {
          setProducts((prev) => prev.filter((p) => p.id !== id));
          notify("已删除", { type: "success" });
        } else {
          notify("删除失败", { type: "error" });
        }
      },
    });
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const res = editingId
        ? await fetch(`${apiUrl}/products/${editingId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ attributes: values.attributes, tags: values.tags }),
          })
        : await fetch(`${apiUrl}/products`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ shop_id: shopId, model: values.model, attributes: values.attributes ?? "", tags: values.tags ?? "" }),
          });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "保存失败"); }
      notify(editingId ? "已更新" : "已创建", { type: "success" });
      setModalOpen(false);
      loadProducts();
    } catch (e: unknown) {
      notify(e instanceof Error ? e.message : "保存失败", { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    const fd = new FormData();
    fd.append("file", file);
    e.target.value = "";
    try {
      const res = await fetch(`${apiUrl}/products/import?shop_id=${shopId}`, { method: "POST", body: fd });
      const data = await res.json();
      notify(data.errors?.length ? `导入完成：成功 ${data.success} 条，${data.errors.length} 错误` : `导入成功 ${data.success} 条`, { type: data.errors?.length ? "warning" : "success" });
      loadProducts();
    } catch {
      notify("导入失败", { type: "error" });
    } finally {
      setImporting(false);
    }
  };

  const columns = [
    { title: "型号", dataIndex: "model", key: "model" },
    {
      title: "属性描述",
      dataIndex: "attributes",
      key: "attributes",
      render: (v: string) => <Tooltip title={v}><Text ellipsis style={{ maxWidth: 300, display: "block" }}>{v || "-"}</Text></Tooltip>,
    },
    {
      title: "标签",
      dataIndex: "tags",
      key: "tags",
      render: (v: string) => v ? v.split(",").map((t) => <Tag key={t}>{t.trim()}</Tag>) : "-",
    },
    {
      title: "Qdrant 同步",
      dataIndex: "qdrant_sync",
      key: "qdrant_sync",
      render: (v: number) => <Tag color={SYNC_MAP[v]?.color}>{SYNC_MAP[v]?.label ?? v}</Tag>,
    },
    { title: "更新时间", dataIndex: "updated_at", key: "updated_at", width: 160 },
    {
      title: "操作",
      key: "actions",
      width: 100,
      render: (_: unknown, record: ProductItem) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)} />
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1100 }}>
      <Title title="产品管理" />
      <ATitle level={4} style={{ marginBottom: 24 }}>产品知识库管理</ATitle>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            value={shopId}
            onChange={setShopId}
            style={{ minWidth: 200 }}
            options={shops.map((s) => ({ value: s.id, label: s.name }))}
          />
          <div style={{ flex: 1 }} />
          <Button icon={<DownloadOutlined />} onClick={() => window.open(`${apiUrl}/products/template/csv`, "_blank")}>
            下载模板
          </Button>
          <Button icon={<UploadOutlined />} loading={importing} onClick={() => fileInputRef.current?.click()}>
            CSV 导入
          </Button>
          <input ref={fileInputRef} type="file" accept=".csv" hidden onChange={handleImport} />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增产品
          </Button>
        </Space>
      </Card>

      <Card>
        <Table dataSource={products} columns={columns} rowKey="id" size="small" loading={loading} />
      </Card>

      <Modal
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        title={editingId ? "编辑产品" : "新增产品"}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          {!editingId && (
            <Form.Item name="model" label="产品型号" rules={[{ required: true, message: "请输入型号" }]}>
              <Input placeholder="如 LED-A19-9W" />
            </Form.Item>
          )}
          <Form.Item name="attributes" label="属性描述" extra="自然语言描述，会固化进 LLM System Prompt">
            <Input.TextArea autoSize={{ minRows: 3 }} placeholder="功率：9W；色温：4000K；接口：E27" />
          </Form.Item>
          <Form.Item name="tags" label="标签" extra="逗号分隔，用于快速检索">
            <Input placeholder="节能,吸顶灯,卧室" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
