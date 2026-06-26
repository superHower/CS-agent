import { useEffect, useState } from "react";
import {
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Switch,
  message,
} from "antd";
import { apiUrl } from "../dataProvider";
import { CATEGORIES } from "../constants/categories";

const PLATFORMS = [
  { value: "taobao", label: "千牛（淘宝）" },
  { value: "pinduoduo", label: "拼多多" },
  { value: "jd", label: "京东" },
  { value: "douyin", label: "抖店" },
];

interface ShopCreateProps {
  open: boolean;
  onClose: () => void;
  /** 打开时默认选中的分类 ID */
  defaultCategory?: string;
  /** 创建成功后回调 */
  onCreated?: () => void;
}

export default function ShopCreate({ open, onClose, defaultCategory, onCreated }: ShopCreateProps) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open) {
      if (defaultCategory) {
        form.setFieldValue("category_id", defaultCategory);
      }
    }
  }, [open, defaultCategory, form]);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      const res = await fetch(`${apiUrl}/shops`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (res.ok || res.status === 201) {
        message.success("新建成功");
        form.resetFields();
        onClose();
        onCreated?.();
      } else {
        const err = await res.json().catch(() => ({}));
        message.error((err as { detail?: string }).detail || "新建失败");
      }
    } catch {
      // validation failed
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = () => {
    form.resetFields();
    onClose();
  };

  return (
    <Modal
      title="新增店铺"
      open={open}
      onCancel={handleCancel}
      onOk={handleOk}
      okText="创建"
      cancelText="取消"
      confirmLoading={loading}
      width={680}
      destroyOnClose
    >
      <Form form={form} layout="vertical" initialValues={{ enabled: true, confidence_threshold: 85 }}>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="shop_id" label="店铺 ID" rules={[{ required: true, message: "请输入店铺 ID" }]}>
              <Input placeholder="如 tb_lamp_001" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="category_id" label="所属分类" rules={[{ required: true, message: "请选择分类" }]}>
              <Select placeholder="请选择分类" options={CATEGORIES.map((c) => ({ value: c.id, label: c.name }))} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="platform" label="平台" rules={[{ required: true, message: "请选择平台" }]}>
              <Select placeholder="请选择平台" options={PLATFORMS} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="name" label="店铺名称" rules={[{ required: true, message: "请输入店铺名称" }]}>
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
      </Form>
    </Modal>
  );
}
