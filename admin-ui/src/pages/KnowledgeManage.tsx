import { useEffect, useState, useRef } from "react";
import { Title, useNotify } from "react-admin";
import {
  Button,
  Card,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
  Modal,
} from "antd";
import { UploadOutlined, DeleteOutlined, FileTextOutlined, EyeOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";
import { useCategories, getCategoryNameById } from "../hooks/useCategories";

const { Title: ATitle, Text } = Typography;

interface ShopOption { id: string; name: string; }

interface KnowledgeFile {
  id: number;
  category_id: string;
  shop_id: string;
  filename: string;
  chunk_count: number;
  total_chars: number;
  status: number;
  raw_content?: string;
  created_at: string;
  updated_at: string;
}

export default function KnowledgeManage() {
  const notify = useNotify();
  const [shops, setShops] = useState<ShopOption[]>([]);
  const [categoryId, setCategoryId] = useState<string>("");
  const [shopId, setShopId] = useState<string>("global");
  const [allShops, setAllShops] = useState<{ shop_id: string; name: string; category_id: string }[]>([]);
  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  // 预览相关
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewFile, setPreviewFile] = useState<KnowledgeFile | null>(null);

  useEffect(() => {
    fetch(`${apiUrl}/shops`)
      .then((r) => r.json())
      .then((data: { shop_id: string; name: string; category_id: string }[]) => {
        if (Array.isArray(data)) {
          setAllShops(data);
          const all = data.map((s) => ({ id: s.shop_id, name: s.name }));
          setShops([{ id: "global", name: "全局（global）" }, ...all]);
        }
      });
  }, []);

  const { categories, loading: catLoading } = useCategories();

  const loadFiles = () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (categoryId) params.set("category_id", categoryId);
    if (shopId) params.set("shop_id", shopId);
    fetch(`${apiUrl}/knowledge/files?${params}`)
      .then((r) => r.json())
      .then((data) => { setFiles(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { notify("加载失败", { type: "error" }); setLoading(false); });
  };

  useEffect(() => { loadFiles(); }, [categoryId, shopId]); // eslint-disable-line

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = Array.from(e.target.files || []);
    if (fileList.length === 0) return;

    setUploading(true);
    let success = 0;
    let failed = 0;
    const errors: string[] = [];

    for (const file of fileList) {
      const ext = file.name.split(".").pop()?.toLowerCase();
      if (ext !== "md") {
        errors.push(`${file.name}: 仅支持 .md 文件`);
        failed++;
        continue;
      }

      const formData = new FormData();
      formData.append("file", file);
      formData.append("category_id", categoryId);
      formData.append("shop_id", shopId);

      const res = await fetch(`${apiUrl}/knowledge/upload`, {
        method: "POST",
        body: formData,
      });

      if (res.ok) {
        success++;
      } else {
        failed++;
        const err = await res.json().catch(() => ({}));
        errors.push(`${file.name}: ${err.detail || "上传失败"}`);
      }
    }

    setUploading(false);
    if (failed === 0 && success > 0) {
      message.success(`上传成功 ${success} 个文件`);
      loadFiles();
    } else if (failed > 0) {
      message.warning(`成功 ${success}，失败 ${failed}`);
      if (errors.length > 0) {
        console.error("上传错误:", errors);
      }
      loadFiles();
    }
    e.target.value = "";
  };

  const handlePreview = async (record: KnowledgeFile) => {
    setPreviewLoading(true);
    setPreviewVisible(true);
    setPreviewFile(null);
    try {
      const res = await fetch(`${apiUrl}/knowledge/files/${record.id}`);
      if (res.ok) {
        const data = await res.json();
        setPreviewFile(data);
      } else {
        message.error("加载文件内容失败");
        setPreviewVisible(false);
      }
    } catch {
      message.error("加载文件内容失败");
      setPreviewVisible(false);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleDelete = (record: KnowledgeFile) => {
    Modal.confirm({
      title: `确认删除 "${record.filename}"？`,
      content: "将同时从知识库中移除所有相关条目",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        const res = await fetch(`${apiUrl}/knowledge/files/${record.id}`, { method: "DELETE" });
        if (res.ok || res.status === 204) {
          notify("已删除", { type: "success" });
          loadFiles();
        } else {
          notify("删除失败", { type: "error" });
        }
      },
    });
  };

  const columns = [
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 80,
      render: (v: number) => (
        <Tag color={v === 1 ? "success" : "default"}>
          {v === 1 ? "已索引" : "未索引"}
        </Tag>
      ),
    },
    {
      title: "文件名",
      dataIndex: "filename",
      key: "filename",
      render: (v: string) => (
        <Space>
          <FileTextOutlined style={{ color: "#1890ff" }} />
          <Text strong>{v}</Text>
        </Space>
      ),
    },
    {
      title: "归属",
      key: "scope",
      width: 140,
      render: (_: unknown, record: KnowledgeFile) => {
        const cat = getCategoryNameById(categories, record.category_id);
        const shop = shops.find((s) => s.id === record.shop_id);
        return <Tag color={record.shop_id === "global" ? "blue" : "green"}>{shop?.name || record.shop_id}</Tag>;
      },
    },
    {
      title: "条目数",
      dataIndex: "chunk_count",
      key: "chunk_count",
      width: 80,
      render: (v: number) => <Text>{v}</Text>,
    },
    {
      title: "字符数",
      dataIndex: "total_chars",
      key: "total_chars",
      width: 100,
      render: (v: number) => <Text type="secondary">{v.toLocaleString()}</Text>,
    },
    {
      title: "上传时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (v: string) => <Text type="secondary">{v}</Text>,
    },
    {
      title: "操作",
      key: "actions",
      width: 120,
      render: (_: unknown, record: KnowledgeFile) => (
        <Space>
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handlePreview(record)}
          />
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record)}
          />
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1000 }}>
      <Title title="知识库管理" />
      <ATitle level={4} style={{ marginBottom: 24 }}>知识文件管理</ATitle>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Text type="secondary">分类：</Text>
          <Select
            placeholder="请先选择分类"
            style={{ minWidth: 180 }}
            value={categoryId || undefined}
            onChange={(v) => { setCategoryId(v ?? ""); setShopId("global"); setFiles([]); }}
            options={categories.filter((c) => c.id !== "default").map((c) => ({ value: c.id, label: c.name }))}
          />
          <Text type="secondary">店铺：</Text>
          <Select
            placeholder="选择店铺"
            style={{ minWidth: 180 }}
            value={shopId || undefined}
            onChange={(v) => setShopId(v ?? "global")}
            allowClear
            options={shops
              .filter((s) => s.id === "global" || allShops.find((a) => a.shop_id === s.id && a.category_id === categoryId))
              .map((s) => ({ value: s.id, label: s.name }))}
          />
          <div style={{ flex: 1 }} />
          <Button
            type="primary"
            icon={<UploadOutlined />}
            onClick={() => fileInputRef.current?.click()}
            loading={uploading}
            disabled={!categoryId}
          >
            上传 MD 文件
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".md"
            multiple
            hidden
            onChange={handleFileUpload}
          />
        </Space>
      </Card>

      {!categoryId ? (
        <Text type="secondary">请先选择分类</Text>
      ) : (
        <Card>
          <Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
            已上传 {files.length} 个文件，共 {files.reduce((acc, f) => acc + f.chunk_count, 0)} 条知识条目
          </Text>
          <Table
            dataSource={files}
            columns={columns}
            rowKey="id"
            size="middle"
            loading={loading}
            pagination={{ pageSize: 20 }}
            locale={{ emptyText: "暂无上传文件，点击「上传 MD 文件」添加" }}
          />
        </Card>
      )}

      {/* 预览弹窗 */}
      <Modal
        title={previewFile?.filename ?? "文件预览"}
        open={previewVisible}
        onCancel={() => setPreviewVisible(false)}
        footer={[
          <Button key="close" onClick={() => setPreviewVisible(false)}>
            关闭
          </Button>,
        ]}
        width={800}
      >
        {previewLoading ? (
          <div style={{ textAlign: "center", padding: 40 }}>加载中...</div>
        ) : previewFile?.raw_content ? (
          <pre
            style={{
              background: "#f5f5f5",
              padding: 16,
              borderRadius: 8,
              maxHeight: 500,
              overflow: "auto",
              fontSize: 13,
              lineHeight: 1.6,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {previewFile.raw_content}
          </pre>
        ) : null}
      </Modal>
    </div>
  );
}
