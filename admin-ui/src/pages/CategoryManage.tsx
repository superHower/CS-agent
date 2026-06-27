import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Col,
  Drawer,
  Form,
  Input,
  List,
  message,
  Popconfirm,
  Row,
  Space,
  Typography,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";

const { Text } = Typography;

interface Category {
  id: string;
  name: string;
}

interface CategoryStats {
  [key: string]: number;
}

export default function CategoryManage({
  open,
  onClose,
  shopCountByCategory,
  onCategoriesChanged,
}: {
  open: boolean;
  onClose: () => void;
  shopCountByCategory: CategoryStats;
  onCategoriesChanged: () => void;
}) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form] = Form.useForm();

  const loadCategories = () => {
    setLoading(true);
    fetch(`${apiUrl}/categories`)
      .then((r) => r.json())
      .then((data: Category[]) => {
        setCategories(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    if (open) loadCategories();
  }, [open]);

  const handleAdd = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      const res = await fetch(`${apiUrl}/categories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: values.id, name: values.name }),
      });
      if (res.ok) {
        message.success("添加成功");
        form.resetFields();
        loadCategories();
        onCategoriesChanged();
      } else {
        const err = await res.json().catch(() => ({}));
        message.error((err as { detail?: string }).detail || "添加失败");
      }
    } catch {
      // validation failed
    } finally {
      setLoading(false);
    }
  };

  const handleUpdate = async (id: string) => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      const res = await fetch(`${apiUrl}/categories/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: values.name }),
      });
      if (res.ok) {
        message.success("更新成功");
        setEditingId(null);
        form.resetFields();
        loadCategories();
        onCategoriesChanged();
      } else {
        const err = await res.json().catch(() => ({}));
        message.error((err as { detail?: string }).detail || "更新失败");
      }
    } catch {
      // validation failed
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (id === "default") {
      message.error("默认分类不能删除");
      return;
    }
    setLoading(true);
    const res = await fetch(`${apiUrl}/categories/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    if (res.ok || res.status === 204) {
      message.success("已删除");
      loadCategories();
      onCategoriesChanged();
    } else {
      const err = await res.json().catch(() => ({}));
      message.error((err as { detail?: string }).detail || "删除失败");
    }
    setLoading(false);
  };

  const startEdit = (cat: Category) => {
    setEditingId(cat.id);
    form.setFieldsValue({ id: cat.id, name: cat.name });
  };

  const cancelEdit = () => {
    setEditingId(null);
    form.resetFields();
  };

  const getShopCount = (id: string) => shopCountByCategory[id] || 0;

  return (
    <Drawer
      title="店铺分类管理"
      placement="right"
      width={400}
      onClose={onClose}
      open={open}
    >
      <Card size="small" style={{ marginBottom: 16 }}>
        <Form form={form} layout="vertical">
          <Row gutter={8}>
            <Col span={10}>
              <Form.Item
                name="id"
                rules={[
                  { required: true, message: "请输入分类 ID" },
                  { pattern: /^[a-z0-9_]+$/, message: "仅支持小写字母、数字、下划线" },
                ]}
              >
                <Input placeholder="分类 ID" disabled={editingId !== null} />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item name="name" rules={[{ required: true, message: "请输入分类名称" }]}>
                <Input placeholder="分类名称" />
              </Form.Item>
            </Col>
            <Col span={4}>
              {editingId ? (
                <Space>
                  <Button type="primary" size="small" onClick={() => handleUpdate(editingId)}>
                    保存
                  </Button>
                  <Button size="small" onClick={cancelEdit}>
                    取消
                  </Button>
                </Space>
              ) : (
                <Button type="primary" size="small" icon={<PlusOutlined />} onClick={handleAdd} loading={loading}>
                  添加
                </Button>
              )}
            </Col>
          </Row>
        </Form>
      </Card>

      <List
        size="small"
        loading={loading}
        dataSource={categories}
        renderItem={(cat) => {
          const shopCount = getShopCount(cat.id);
          const isDefault = cat.id === "default";
          const isEditing = editingId === cat.id;

          return (
            <List.Item
              key={cat.id}
              actions={
                isEditing
                  ? []
                  : [
                      <Button
                        key="edit"
                        type="text"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() => startEdit(cat)}
                      />,
                      isDefault ? null : (
                        <Popconfirm
                          key="delete"
                          title="确认删除"
                          description={
                            shopCount > 0 ? (
                              <Text type="danger">
                                当前分类下有 <strong>{shopCount}</strong> 个店铺，删除后这些店铺将变为默认分类，是否继续？
                              </Text>
                            ) : (
                              "确定要删除该分类吗？"
                            )
                          }
                          onConfirm={() => handleDelete(cat.id)}
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true }}
                        >
                          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                        </Popconfirm>
                      ),
                    ].filter(Boolean)
              }
            >
              <List.Item.Meta
                title={
                  isEditing ? (
                    <Text type="secondary">{cat.id}</Text>
                  ) : (
                    <Text>{cat.name}</Text>
                  )
                }
                description={
                  isEditing ? null : (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      ID: {cat.id} · {shopCount} 个店铺
                    </Text>
                  )
                }
              />
            </List.Item>
          );
        }}
      />
    </Drawer>
  );
}
