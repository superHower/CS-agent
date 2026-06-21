import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CardHeader,
  CircularProgress,
  Link,
  TextField,
  Typography,
} from "@mui/material";
import SaveIcon from "@mui/icons-material/Save";
import NotificationsActiveIcon from "@mui/icons-material/NotificationsActive";
import { apiUrl } from "../dataProvider";

interface AlertConfig {
  webhook_url: string;
  updated_at: string;
}

export default function AlertConfig() {
  const [config, setConfig] = useState<AlertConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const notify = useNotify();

  useEffect(() => {
    fetch(`${apiUrl}/alert-config`)
      .then((r) => r.json())
      .then((data) => {
        setConfig(data);
        setLoading(false);
      })
      .catch(() => {
        notify("加载告警配置失败", { type: "error" });
        setLoading(false);
      });
  }, [notify]);

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      const res = await fetch(`${apiUrl}/alert-config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ webhook_url: config.webhook_url }),
      });
      if (!res.ok) throw new Error(await res.text());
      const updated = await res.json();
      setConfig(updated);
      notify("告警配置已保存", { type: "success" });
    } catch {
      notify("保存失败", { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" mt={6}>
        <CircularProgress />
      </Box>
    );
  }

  if (!config) return null;

  return (
    <Box p={3} maxWidth={680}>
      <Title title="告警配置" />
      <Typography variant="h5" fontWeight="bold" mb={3}>
        企业微信告警配置
      </Typography>

      <Alert severity="info" sx={{ mb: 3 }} icon={<NotificationsActiveIcon />}>
        当会话触发转人工时（敏感词、低置信度、系统异常），系统将自动向企业微信群机器人发送告警通知。
      </Alert>

      <Card elevation={2}>
        <CardHeader
          title="企业微信机器人"
          subheader={
            config.updated_at ? `上次更新：${config.updated_at}` : "尚未配置"
          }
        />
        <CardContent>
          <Box display="flex" flexDirection="column" gap={3}>
            <TextField
              label="Webhook 地址"
              value={config.webhook_url}
              onChange={(e) =>
                setConfig({ ...config, webhook_url: e.target.value })
              }
              fullWidth
              placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
              helperText={
                <>
                  在企业微信群中添加「群机器人」后获取 Webhook 地址。
                  <Link
                    href="https://developer.work.weixin.qq.com/document/path/91770"
                    target="_blank"
                    rel="noopener"
                    sx={{ ml: 0.5 }}
                  >
                    查看文档
                  </Link>
                </>
              }
            />

            {config.webhook_url && (
              <Alert severity="success">
                已配置 Webhook，转人工事件将实时推送到企业微信群。
              </Alert>
            )}

            <Button
              variant="contained"
              startIcon={saving ? <CircularProgress size={16} /> : <SaveIcon />}
              onClick={handleSave}
              disabled={saving}
              sx={{ alignSelf: "flex-start" }}
            >
              保存配置
            </Button>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
