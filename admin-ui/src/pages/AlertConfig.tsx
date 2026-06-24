import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import { Alert, Button, Card, Form, Input, Spin, Typography } from "antd";
import { SaveOutlined, NotificationOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";

const { Title: ATitle, Text } = Typography;

interface AlertConfigData {
  webhook_url: string;
  updated_at: string;
}

export default function AlertConfig() {
  const [config, setConfig] = useState<AlertConfigData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const notify = useNotify();

  useEffect(() => {
    fetch(`${apiUrl}/alert-config`)
      .then((r) => r.json())
      .then((data) => { setConfig(data); form.setFieldsValue(data); setLoading(false); })
      .catch(() => { notify("加载告警配置失败", { type: "error" }); setLoading(false); });
  }, [notify, form]);

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const res = await fetch(`${apiUrl}/alert-config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!res.ok) throw new Error(await res.text());
      const updated = await res.json();
      setConfig(updated);
      form.setFieldsValue(updated);
      notify("告警配置已保存", { type: "success" });
    } catch {
      notify("保存失败", { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div style={{ display: "flex", justifyContent: "center", marginTop: 48 }}><Spin size="large" /></div>;
  if (!config) return null;

  return (
    <div style={{ padding: 24, maxWidth: 680 }}>
      <Title title="告警配置" />
      <ATitle level={4} style={{ marginBottom: 24 }}>企业微信告警配置</ATitle>

      <Alert
        icon={<NotificationOutlined />}
        showIcon
        type="info"
        message="当会话触发转人工时（敏感词、低置信度、系统异常），系统将自动向企业微信群机器人发送告警通知。"
        style={{ marginBottom: 24 }}
      />

      <Card
        title="企业微信机器人"
        extra={config.updated_at ? <Text type="secondary">上次更新：{config.updated_at}</Text> : "尚未配置"}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="webhook_url"
            label="Webhook 地址"
            extra={<>在企业微信群中添加「群机器人」后获取 Webhook 地址。<a href="https://developer.work.weixin.qq.com/document/path/91770" target="_blank" rel="noopener"> 查看文档</a></>}
          >
            <Input placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..." />
          </Form.Item>

          {config.webhook_url && (
            <Alert type="success" message="已配置 Webhook，转人工事件将实时推送到企业微信群。" style={{ marginBottom: 16 }} />
          )}

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
