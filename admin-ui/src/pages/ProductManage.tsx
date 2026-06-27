import { useEffect, useState, useRef } from "react";
import { Title, useNotify } from "react-admin";
import {
  Button,
  Card,
  Cascader,
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
import { useCategories, getCategoryNameById } from "../hooks/useCategories";

const { Title: ATitle, Text } = Typography;

interface ShopOption { id: string; name: string; }

interface ProductItem {
  id: number;
  category_id: string;
  shop_id: string;
  model: string;
  attributes: string;
  tags: string;
  qdrant_sync: number;
  created_at: string;
  updated_at: string;
}

const SYNC_MAP: Record<number, { label: string; color: string }> = {
  1: { label: "已同步", color: "success" },
  0: { label: "待同步", color: "default" },
  [-1]: { label: "同步失败", color: "error" },
};

export default function ProductManage() {
  const notify = useNotify();
  const [shops, setShops] = useState<ShopOption[]>([]);
  const [allShops, setAllShops] = useState<{ shop_id: string; name: string; category_id: string }[]>([]);
  const [categoryId, setCategoryId] = useState<string>("");
  const [selectedShopIds, setSelectedShopIds] = useState<string[]>([]);
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [modalCategoryId, setModalCategoryId] = useState("");
  const [modalShopIds, setModalShopIds] = useState<string[]>([]);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    fetch(`${apiUrl}/shops`)
      .then((r) => r.json())
      .then((data: { shop_id: string; name: string; category_id: string }[]) => {
        if (Array.isArray(data)) {
          setAllShops(data);
          setShops([{ id: "global", name: "全店铺适用" }, ...data.map((s) => ({ id: s.shop_id, name: s.name }))]);
        }
      });
  }, []);

  const { categories, loading: catLoading } = useCategories();

  const loadProducts = () => {
    if (!categoryId) return;
    setLoading(true);
    const params = new URLSearchParams();
    params.set("category_id", categoryId);
    if (selectedShopIds.length === 1) params.set("shop_id", selectedShopIds[0]);
    fetch(`${apiUrl}/products?${params}`)
      .then((r) => r.json())
      .then((data) => {
        const items = Array.isArray(data) ? data : (data.items ?? []);
        setProducts(items);
        setLoading(false);
      })
      .catch(() => { notify("加载产品失败", { type: "error" }); setLoading(false); });
  };

  useEffect(() => { loadProducts(); }, [categoryId, selectedShopIds]); // eslint-disable-line

  const handleDelete = (id: number) => {
    Modal.confirm({
      title: "确认删除该产品？",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        const res = await fetch(`${apiUrl}/products/${id}`, { method: "DELETE" });
        if (res.ok || res.status === 204) {
          notify("已删除", { type: "success" });
          loadProducts();
        } else {
          notify("删除失败", { type: "error" });
        }
      },
    });
  };

  const openCreate = () => {
    setEditingId(null);
    setModalCategoryId(categoryId);
    setModalShopIds(selectedShopIds.length ? selectedShopIds : []);
    setModalOpen(true);
  };

  const openEdit = (p: ProductItem) => {
    setEditingId(p.id);
    setModalCategoryId(p.category_id);
    setModalShopIds([p.shop_id]);
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const shopIds = modalShopIds.length > 0 ? modalShopIds : ["global"];
      const categoryIdVal = modalCategoryId || values.category_id;
      if (!categoryIdVal) {
        notify("请选择分类", { type: "warning" });
        return;
      }
      setSaving(true);

      let success = 0;
      for (const shop_id of shopIds) {
        const payload = { ...values, category_id: categoryIdVal, shop_id };
        const method = editingId ? "PUT" : "POST";
        const url = editingId ? `${apiUrl}/products/${editingId}` : `${apiUrl}/products`;
        const res = await fetch(url, {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok && res.status !== 201) {
          const err = await res.json().catch(() => ({}));
          throw new Error((err as { detail?: string }).detail || "保存失败");
        }
        success++;
      }
      notify(`${editingId ? "更新" : "创建"}成功（已保存至 ${success} 个店铺）`, { type: "success" });
      setModalOpen(false);
      loadProducts();
    } catch (err) {
      notify(err instanceof Error ? err.message : "保存失败", { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !categoryId) return;
    setImporting(true);
    const fd = new FormData();
    fd.append("file", file);
    e.target.value = "";
    try {
      const res = await fetch(`${apiUrl}/products/import?category_id=${categoryId}&shop_id=${selectedShopIds[0] || "global"}`, { method: "POST", body: fd });
      const data = await res.json();
      if (data.errors?.length) {
        notify(`导入完成：成功 ${data.success} 条，${data.errors.length} 条错误`, { type: "warning" });
      } else {
        notify(`导入成功 ${data.success} 条`, { type: "success" });
      }
      loadProducts();
    } catch {
      notify("导入失败", { type: "error" });
    } finally {
      setImporting(false);
    }
  };

  const columns = [
    {
      title: "分类",
      dataIndex: "category_id",
      key: "category_id",
      width: 80,
      render: (v: string) => <Tag>{getCategoryNameById(categories, v)}</Tag>,
    },
    {
      title: "归属",
      key: "scope",
      width: 120,
      render: (_: unknown, record: ProductItem) => {
        const shop = shops.find((s) => s.id === record.shop_id);
        return <Tag color={record.shop_id === "global" ? "blue" : "green"}>{shop?.name || record.shop_id}</Tag>;
      },
    },
    {
      title: "型号",
      dataIndex: "model",
      key: "model",
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: "属性",
      dataIndex: "attributes",
      key: "attributes",
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{v || "-"}</Text>,
    },
    {
      title: "标签",
      dataIndex: "tags",
      key: "tags",
      width: 120,
      render: (v: string) => v ? v.split(",").slice(0, 3).map((t: string, i: number) => <Tag key={i}>{t.trim()}</Tag>) : <Text type="secondary">-</Text>,
    },
    {
      title: "同步",
      dataIndex: "qdrant_sync",
      key: "qdrant_sync",
      width: 80,
      render: (v: number) => <Tag color={SYNC_MAP[v]?.color}>{SYNC_MAP[v]?.label || v}</Tag>,
    },
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
      <ATitle level={4} style={{ marginBottom: 24 }}>产品型号管理</ATitle>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Cascader
            placeholder="选择分类和店铺"
            style={{ minWidth: 280 }}
            value={categoryId ? [[categoryId, ...selectedShopIds]] : []}
            onChange={(v) => {
              const path = (v as string[][])[0] || [];
              setCategoryId(path[0] || "");
              setSelectedShopIds(path.slice(1));
              setProducts([]);
            }}
            options={categories
              .filter((c) => c.id !== "default")
              .map((cat) => ({
                value: cat.id,
                label: cat.name,
                children: allShops
                  .filter((s) => s.category_id === cat.id)
                  .map((s) => ({ value: s.shop_id, label: s.name })),
              }))}
            expandTrigger="hover"
            multiple
            changeOnSelect
            displayRender={(labels) => labels.join(" / ")}
          />
          <div style={{ flex: 1 }} />
          <Button icon={<DownloadOutlined />} onClick={() => window.open(`${apiUrl}/products/template/csv`, "_blank")}>
            下载模板
          </Button>
          <Button
            icon={<UploadOutlined />}
            onClick={() => fileInputRef.current?.click()}
            disabled={!categoryId || importing}
            loading={importing}
          >
            CSV 导入
          </Button>
          <input ref={fileInputRef} type="file" accept=".csv" hidden onChange={handleImport} />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} disabled={!categoryId}>
            新增产品
          </Button>
        </Space>
      </Card>

      {!categoryId ? (
        <Text type="secondary">请先选择分类</Text>
      ) : (
        <Card>
          <Table
            dataSource={products}
            columns={columns}
            rowKey="id"
            size="small"
            loading={loading}
            pagination={{ pageSize: 20 }}
            locale={{ emptyText: "暂无产品，点击「新增产品」添加" }}
          />
        </Card>
      )}

      <Modal
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        title={editingId ? "编辑产品" : "新增产品"}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item label="分类" style={{ marginBottom: 12 }}>
            <Cascader
              style={{ minWidth: 240 }}
              placeholder="选择分类和店铺"
              value={modalCategoryId ? [[modalCategoryId, ...modalShopIds]] : []}
              onChange={(v) => {
                const path = (v as string[][])[0] || [];
                setModalCategoryId(path[0] || "");
                setModalShopIds(path.slice(1));
              }}
              options={categories
                .filter((c) => c.id !== "default")
                .map((cat) => ({
                  value: cat.id,
                  label: cat.name,
                  children: [
                    { value: "global", label: "全店铺适用" },
                    ...allShops
                      .filter((s) => s.category_id === cat.id)
                      .map((s) => ({ value: s.shop_id, label: s.name })),
                  ],
                }))}
              expandTrigger="hover"
              multiple
              changeOnSelect
            />
          </Form.Item>
          <Form.Item name="model" label="产品型号" rules={[{ required: true, message: "请输入型号" }]}>
            <Input placeholder="如 ALS-2024-Pro" />
          </Form.Item>
          <Form.Item name="attributes" label="产品属性">
            <Input.TextArea placeholder="如 功率：36W，色温：3000-6500K" rows={2} />
          </Form.Item>
          <Form.Item name="tags" label="标签">
            <Input placeholder="多个标签用逗号分隔" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
