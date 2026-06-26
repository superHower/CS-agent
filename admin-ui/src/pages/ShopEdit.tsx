import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Switch,
  Typography,
  message,
  Space,
} from "antd";
import { ArrowLeftOutlined, SaveOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";
import { useCategories } from "../hooks/useCategories";
import { useNavigate, useParams } from "react-router-dom";

const { Title: ATitle } = Typography;

const PLATFORMS = [
  { value: "taobao", label: "千牛（淘宝）" },
  { value: "pinduoduo", label: "拼多多" },
  { value: "jd", label: "京东" },
  { value: "douyin", label: "抖店" },
];

interface ShopData {
  shop_id: string;
  category_id: string;
  platform: string;
  name: string;
  obsidian_vault: string;
  api_key: string;
  confidence_threshold: number;
  enabled: boolean;
}

export default function ShopEdit() {
  const navigate = useNavigate();
  const params = useParams();
  const shopId = params.id;
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [initLoading, setInitLoading] = useState(true);
  const { categories, loading: catLoading, reload: reloadCategories } = useCategories();

  useEffect(() => {
    if (!shopId) {
      message.error("店铺 ID 不存在");
      navigate("/shops");
      return;
    }
    fetch(`${apiUrl}/shops`)
      .then((r) => r.json())
      .then((data: ShopData[]) => {
        const shop = Array.isArray(data) ? data.find((s) => s.shop_id === shopId) : null;
        if (shop) {
          form.setFieldsValue(shop);
        } else {
          message.error("店铺不存在");
          navigate("/shops");
        }
        setInitLoading(false);
      })
      .catch(() => {
        message.error("加载失败");
        setInitLoading(false);
      });
  }, [shopId, form, navigate]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      const res = await fetch(`${apiUrl}/shops/${encodeURIComponent(shopId!)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (res.ok || res.status === 200) {
        message.success("保存成功");
        reloadCategories();
        navigate("/shops");
      } else {
        const err = await res.json().catch(() => ({}));
        message.error((err as { detail?: string }).detail || "保存失败");
      }
    } catch {
      // validation failed
    } finally {
      setLoading(false);
    }
  };

  const categoryOptions = categories.map((c) => ({ value: c.id, label: c.name }));

  return (
    <div style={{ padding: 24, maxWidth: 800 }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/shops")}>
          返回店铺列表
        </Button>
      </Space>

      <ATitle level={4}>编辑店铺信息</ATitle>

      <Card loading={initLoading}>
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="shop_id" label="店铺 ID">
                <Input disabled />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="category_id"
                label="所属分类"
                rules={[{ required: true, message: "请选择或输入分类" }]}
                extra="可选择现有分类或输入新的分类 ID"
              >
                <Select
                  showSearch
                  allowClear
                  placeholder="请选择分类"
                  loading={catLoading}
                  options={categoryOptions}
                  filterOption={(input, option) =>
                    (option?.label ?? "").toLowerCase().includes(input.toLowerCase()) ||
                    (option?.value ?? "").toLowerCase().includes(input.toLowerCase())
                  }
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="platform" label="平台">
                <Input disabled />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="name"
                label="店铺名称"
                rules={[{ required: true, message: "请输入店铺名称" }]}
              >
                <Input placeholder="请输入店铺名称" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="obsidian_vault" label="知识库路径">
                <Input placeholder="如 data/obsidian/tb_lamp_001" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="api_key" label="平台 API Key">
                <Input placeholder="请输入 API Key" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="api_secret" label="平台 API Secret">
                <Input.Password placeholder="请输入 API Secret" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="confidence_threshold" label="置信度阈值（%）">
                <InputNumber min={0} max={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="enabled" label="启用" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>

          <Space style={{ marginTop: 24 }}>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleSave}
              loading={loading}
            >
              保存
            </Button>
            <Button onClick={() => navigate("/shops")}>取消</Button>
          </Space>
        </Form>
      </Card>
    </div>
  );
}
