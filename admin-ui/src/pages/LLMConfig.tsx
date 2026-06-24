import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import { Button, Card, Form, Input, Slider, Space, Spin, Typography } from "antd";
import { SaveOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";

const { Title: ATitle, Text } = Typography;

const PROVIDERS = [
  { label: "DeepSeek", base_url: "https://api.deepseek.com/v1" },
  { label: "通义千问", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
];

interface LLMConfigData {
  model: string;
  api_key: string;
  base_url: string;
  max_tokens: number;
  temperature: number;
  timeout: number;
  embedding_model: string;
  updated_at: string;
}

export default function LLMConfig() {
  const [config, setConfig] = useState<LLMConfigData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const notify = useNotify();

  useEffect(() => {
    fetch(`${apiUrl}/llm-config`)
      .then((r) => r.json())
      .then((data) => { setConfig(data); form.setFieldsValue(data); setLoading(false); })
      .catch(() => { notify("加载 LLM 配置失败", { type: "error" }); setLoading(false); });
  }, [notify, form]);

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const res = await fetch(`${apiUrl}/llm-config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!res.ok) throw new Error(await res.text());
      const updated = await res.json();
      setConfig(updated);
      form.setFieldsValue(updated);
      notify("LLM 配置已保存", { type: "success" });
    } catch {
      notify("保存失败", { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div style={{ display: "flex", justifyContent: "center", marginTop: 48 }}><Spin size="large" /></div>;
  if (!config) return null;

  return (
    <div style={{ padding: 24, maxWidth: 760 }}>
      <Title title="LLM 配置" />
      <ATitle level={4} style={{ marginBottom: 24 }}>LLM 推理配置</ATitle>

      <Card
        title="云端模型"
        extra={config.updated_at ? <Text type="secondary">上次更新：{config.updated_at}</Text> : "尚未配置"}
      >
        <Form form={form} layout="vertical">
          <Form.Item label="供应商快捷填入">
            <Space>
              {PROVIDERS.map((p) => (
                <Button
                  key={p.base_url}
                  type={form.getFieldValue("base_url") === p.base_url ? "primary" : "default"}
                  onClick={() => form.setFieldValue("base_url", p.base_url)}
                >
                  {p.label}
                </Button>
              ))}
            </Space>
          </Form.Item>

          <Form.Item name="base_url" label="API Base URL" extra="OpenAI 兼容接口地址，点击上方按钮快捷填入">
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item name="model" label="模型名称" extra="如 deepseek-chat、qwen-turbo、qwen-max 等">
            <Input placeholder="deepseek-chat" />
          </Form.Item>

          <Form.Item name="api_key" label="API Key" extra="填写后保存">
            <Input.Password placeholder="sk-..." />
          </Form.Item>

          <Form.Item name="embedding_model" label="文本嵌入模型" extra="本地路径（如 models/bge-small-zh）或 HuggingFace 模型名">
            <Input placeholder="BAAI/bge-small-zh-v1.5" />
          </Form.Item>

          <Form.Item name="temperature" label={`Temperature（采样温度）：${form.getFieldValue("temperature") ?? config.temperature}`}>
            <Slider
              min={0} max={2} step={0.05}
              marks={{ 0: "0", 0.3: "0.3", 1: "1", 2: "2" }}
            />
          </Form.Item>

          <Form.Item name="max_tokens" label="Max Tokens">
            <Input type="number" min={1} max={32768} />
          </Form.Item>

          <Form.Item name="timeout" label="超时秒数（超时转人工）">
            <Input type="number" min={1} max={60} step={0.5} />
          </Form.Item>

          <Form.Item>
            <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
              保存配置
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
