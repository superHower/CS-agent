import { useEffect, useState, useRef } from "react";
import { Title, useNotify } from "react-admin";
import {
  Button,
  Card,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
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

interface FaqAlias {
  id?: number;
  faq_id?: number;
  question: string;
  is_primary: boolean;
}

interface FaqItem {
  id: number;
  category_id: string;
  shop_id: string;
  answer: string;
  sub_tag: string;
  priority: number;
  enabled: boolean;
  aliases: FaqAlias[];
  created_at: string;
  updated_at: string;
}

const EMPTY_FORM = {
  category_id: "",
  shop_ids: [] as string[],
  answer: "",
  sub_tag: "",
  priority: 0,
  enabled: true,
  aliases: [{ question: "", is_primary: true }] as FaqAlias[],
};

export default function FaqManage() {
  const notify = useNotify();
  const [shops, setShops] = useState<ShopOption[]>([]);
  const [categoryId, setCategoryId] = useState<string>("");
  const [selectedShopId, setSelectedShopId] = useState<string>("");
  const [allShops, setAllShops] = useState<{ shop_id: string; name: string; category_id: string }[]>([]);
  const [faqTag, setFaqTag] = useState<string>("");
  const [faqs, setFaqs] = useState<FaqItem[]>([]);
  const [loading, setLoading] = useState(false);
  const { categories, loading: catLoading } = useCategories();

  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    fetch(`${apiUrl}/shops`)
      .then((r) => r.json())
      .then((data: { shop_id: string; name: string; category_id: string }[]) => {
        if (Array.isArray(data)) {
          setAllShops(data);
          setShops(data.map((s) => ({ id: s.shop_id, name: s.name })));
        }
      });
  }, []);

  useEffect(() => {
    if (!catLoading && categories.length > 0 && !categoryId) {
      const firstCat = categories.find((c) => c.id !== "default");
      if (firstCat) setCategoryId(firstCat.id);
    }
  }, [categories, catLoading]);

  const loadFaqs = () => {
    if (!categoryId) return;
    setLoading(true);
    const params = new URLSearchParams();
    params.set("category_id", categoryId);
    if (selectedShopId) params.set("shop_id", selectedShopId);
    if (faqTag) params.set("sub_tag", faqTag);
    fetch(`${apiUrl}/faqs?${params}`)
      .then((r) => r.json())
      .then((data) => { setFaqs(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { notify("加载 FAQ 失败", { type: "error" }); setLoading(false); });
  };

  useEffect(() => { loadFaqs(); }, [categoryId, selectedShopId, faqTag]); // eslint-disable-line

  const handleToggle = async (faq: FaqItem) => {
    const res = await fetch(`${apiUrl}/faqs/${faq.id}/enabled?enabled=${!faq.enabled}`, { method: "PATCH" });
    if (res.ok) {
      setFaqs((prev) => prev.map((f) => f.id === faq.id ? { ...f, enabled: !faq.enabled } : f));
    } else {
      notify("操作失败", { type: "error" });
    }
  };

  const handleDelete = (id: number) => {
    Modal.confirm({
      title: "确认删除该 FAQ？",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        const res = await fetch(`${apiUrl}/faqs/${id}`, { method: "DELETE" });
        if (res.ok || res.status === 204) {
          setFaqs((prev) => prev.filter((f) => f.id !== id));
          notify("已删除", { type: "success" });
        } else {
          notify("删除失败", { type: "error" });
        }
      },
    });
  };

  const openCreate = () => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM, category_id: categoryId, shop_ids: selectedShopId ? [selectedShopId] : [] });
    setModalOpen(true);
  };

  const openEdit = (faq: FaqItem) => {
    setEditingId(faq.id);
    setForm({
      category_id: faq.category_id,
      shop_ids: [faq.shop_id],
      answer: faq.answer,
      sub_tag: faq.sub_tag,
      priority: faq.priority,
      enabled: faq.enabled,
      aliases: faq.aliases.map((a) => ({ question: a.question, is_primary: a.is_primary })),
    });
    setModalOpen(true);
  };

  const addAlias = () =>
    setForm((f) => ({ ...f, aliases: [...f.aliases, { question: "", is_primary: false }] }));

  const removeAlias = (i: number) =>
    setForm((f) => {
      const aliases = f.aliases.filter((_, idx) => idx !== i);
      if (!aliases.some((a) => a.is_primary) && aliases.length > 0) aliases[0].is_primary = true;
      return { ...f, aliases };
    });

  const updateAlias = (i: number, field: keyof FaqAlias, value: string | boolean) =>
    setForm((f) => {
      const aliases = f.aliases.map((a, idx) => {
        if (idx !== i) return field === "is_primary" && value ? { ...a, is_primary: false } : a;
        return { ...a, [field]: value };
      });
      return { ...f, aliases };
    });

  const handleSave = async () => {
    const emptyAlias = form.aliases.find((a) => !a.question.trim());
    if (emptyAlias !== undefined) { notify("问法不能为空", { type: "warning" }); return; }
    if (!form.answer.trim()) { notify("回复内容不能为空", { type: "warning" }); return; }
    if (!form.category_id) { notify("请先选择分类", { type: "warning" }); return; }

    setSaving(true);
    const isCategoryLevel = form.shop_ids.length === 0;
    try {
      const body = {
        category_id: form.category_id,
        answer: form.answer,
        sub_tag: form.sub_tag,
        priority: form.priority,
        enabled: form.enabled,
        aliases: form.aliases,
      };

      if (editingId) {
        const res = await fetch(`${apiUrl}/faqs/${editingId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answer: body.answer, sub_tag: body.sub_tag, priority: body.priority, enabled: body.enabled, aliases: body.aliases }),
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "保存失败");
        }
        notify("更新成功", { type: "success" });
      } else {
        if (isCategoryLevel) {
          body.shop_ids = [];
        } else {
          for (const shop_id of form.shop_ids) {
            const res = await fetch(`${apiUrl}/faqs`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ...body, shop_id }),
            });
            if (!res.ok) {
              const err = await res.json();
              throw new Error(err.detail || "保存失败");
            }
          }
          notify(`创建成功（已保存至 ${form.shop_ids.length} 个店铺）`, { type: "success" });
          setModalOpen(false);
          loadFaqs();
          setSaving(false);
          return;
        }
        const res = await fetch(`${apiUrl}/faqs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "保存失败");
        }
        notify("创建成功（已保存至该分类所有店铺）", { type: "success" });
      }
      setModalOpen(false);
      loadFaqs();
    } catch (err) {
      notify((err as Error).message, { type: "error" });
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
      const res = await fetch(`${apiUrl}/faqs/import?category_id=${categoryId}&shop_id=${selectedShopId || "global"}`, { method: "POST", body: fd });
      const data = await res.json();
      if (data.errors?.length) {
        notify(`导入完成：成功 ${data.success} 条，${data.errors.length} 条错误`, { type: "warning" });
      } else {
        notify(`导入成功 ${data.success} 条`, { type: "success" });
      }
      loadFaqs();
    } catch {
      notify("导入失败", { type: "error" });
    } finally {
      setImporting(false);
    }
  };

  const faqTagOptions = Array.from(new Set(faqs.map((f) => f.sub_tag).filter(Boolean)));

  const columns = [
    {
      title: "启用",
      dataIndex: "enabled",
      key: "enabled",
      width: 60,
      render: (enabled: boolean, record: FaqItem) => (
        <Switch size="small" checked={enabled} onChange={() => handleToggle(record)} />
      ),
    },
    { title: "优先级", dataIndex: "priority", key: "priority", width: 80 },
    {
      title: "子标签",
      dataIndex: "sub_tag",
      key: "sub_tag",
      width: 100,
      render: (v: string) => v ? <Tag>{v}</Tag> : "-",
    },
    {
      title: "归属",
      key: "scope",
      width: 140,
      render: (_: unknown, record: FaqItem) => {
        const catName = getCategoryNameById(categories, record.category_id);
        const shopName = record.shop_id === "global" ? "共享" : (shops.find((s) => s.id === record.shop_id)?.name || record.shop_id);
        return <Tag color={record.shop_id === "global" ? "blue" : "green"}>{shopName}</Tag>;
      },
    },
    {
      title: "主问法",
      key: "primary",
      render: (_: unknown, record: FaqItem) => {
        const primary = record.aliases.find((a) => a.is_primary) || record.aliases[0];
        return <Text>{primary?.question || "-"}</Text>;
      },
    },
    {
      title: "别名数",
      key: "alias_count",
      width: 80,
      render: (_: unknown, record: FaqItem) => <Tag>{record.aliases.length}</Tag>,
    },
    {
      title: "回复预览",
      dataIndex: "answer",
      key: "answer",
      render: (v: string) => (
        <Tooltip title={v}>
          <Text ellipsis style={{ maxWidth: 200, display: "block" }}>{v}</Text>
        </Tooltip>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 100,
      render: (_: unknown, record: FaqItem) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)} />
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1200 }}>
      <Title title="FAQ 管理" />
      <ATitle level={4} style={{ marginBottom: 24 }}>FAQ 知识库管理</ATitle>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder="选择分类"
            style={{ minWidth: 180 }}
            value={categoryId || undefined}
            onChange={(v) => {
              setCategoryId(v ?? "");
              setSelectedShopId("");
              setFaqs([]);
            }}
            allowClear
            options={categories
              .filter((c) => c.id !== "default")
              .map((cat) => ({ value: cat.id, label: cat.name }))}
          />
          <Select
            placeholder="选择店铺"
            style={{ minWidth: 200 }}
            value={selectedShopId || undefined}
            onChange={(v) => {
              setSelectedShopId(v ?? "");
              setFaqs([]);
            }}
            allowClear
            options={allShops
              .filter((s) => !categoryId || s.category_id === categoryId)
              .map((s) => ({ value: s.shop_id, label: s.name }))}
          />
          <Select
            placeholder="标签筛选"
            style={{ minWidth: 150 }}
            value={faqTag || undefined}
            onChange={(v) => setFaqTag(v ?? "")}
            allowClear
            options={faqTagOptions.map((c) => ({ value: c, label: c }))}
          />
          <div style={{ flex: 1 }} />
          <Button icon={<DownloadOutlined />} onClick={() => window.open(`${apiUrl}/faqs/template/csv`, "_blank")}>
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
            新增 FAQ
          </Button>
        </Space>
      </Card>

      {!categoryId ? (
        <Text type="secondary">请先选择分类</Text>
      ) : (
        <Card>
          <Table
            dataSource={faqs}
            columns={columns}
            rowKey="id"
            size="small"
            loading={loading}
            pagination={false}
            rowClassName={(r) => r.enabled ? "" : "opacity-50"}
            locale={{ emptyText: "暂无 FAQ，点击「新增 FAQ」添加" }}
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
        title={editingId ? "编辑 FAQ" : "新增 FAQ"}
        width={560}
        destroyOnHidden
      >
        <Form layout="vertical" style={{ marginTop: 16 }}>
          <Space style={{ width: "100%" }} size={12} wrap>
            <Form.Item label="分类" style={{ minWidth: 140 }} required>
              <Select
                style={{ minWidth: 160 }}
                value={form.category_id || undefined}
                onChange={(v) => setForm({ ...form, category_id: v ?? "", shop_ids: [] })}
                allowClear
                placeholder="选择分类"
                options={categories
                  .filter((c) => c.id !== "default")
                  .map((cat) => ({ value: cat.id, label: cat.name }))}
              />
            </Form.Item>
            <Form.Item label="店铺" style={{ minWidth: 200 }} extra="不选则应用至该分类所有店铺">
              <Select
                style={{ minWidth: 200 }}
                value={form.shop_ids.length > 0 ? form.shop_ids : undefined}
                onChange={(v) => setForm({ ...form, shop_ids: v ?? [] })}
                allowClear
                mode="multiple"
                maxTagCount={2}
                placeholder="不选则应用至该分类所有店铺"
                options={allShops
                  .filter((s) => s.category_id === form.category_id)
                  .map((s) => ({ value: s.shop_id, label: s.name }))}
              />
            </Form.Item>
          </Space>

          <Form.Item label="问法列表（至少填写一条，第一条为主问法）" required>
            {form.aliases.map((alias, i) => (
              <Space key={i} align="center" style={{ marginBottom: 8, width: "100%" }}>
                <Input
                  placeholder={alias.is_primary ? "主问法" : `别名 ${i}`}
                  value={alias.question}
                  onChange={(e) => updateAlias(i, "question", e.target.value)}
                  style={{ width: 300 }}
                />
                <Tooltip title="设为主问法">
                  <Tag
                    color={alias.is_primary ? "blue" : "default"}
                    style={{ cursor: "pointer" }}
                    onClick={() => updateAlias(i, "is_primary", true)}
                  >
                    主
                  </Tag>
                </Tooltip>
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => removeAlias(i)}
                  disabled={form.aliases.length === 1}
                />
              </Space>
            ))}
            <Button size="small" icon={<PlusOutlined />} onClick={addAlias}>添加别名</Button>
          </Form.Item>

          <Divider />

          <Form.Item label="回复内容" required extra="买家问法命中时，直接发送此内容，不经过 LLM">
            <Input.TextArea
              value={form.answer}
              onChange={(e) => setForm({ ...form, answer: e.target.value })}
              autoSize={{ minRows: 3 }}
            />
          </Form.Item>

          <Space style={{ width: "100%" }} size={16}>
            <Form.Item label="子标签" extra="如：发货、退款、产品" style={{ flex: 1 }}>
              <Input
                value={form.sub_tag}
                onChange={(e) => setForm({ ...form, sub_tag: e.target.value })}
              />
            </Form.Item>
            <Form.Item label="优先级" extra="0-100，越大越优先">
              <InputNumber
                min={0} max={100}
                value={form.priority}
                onChange={(v) => setForm({ ...form, priority: v ?? 0 })}
                style={{ width: 120 }}
              />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  );
}
