import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import {
  Box,
  Button,
  Card,
  CardContent,
  CardHeader,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Slider,
  TextField,
  Typography,
} from "@mui/material";
import SaveIcon from "@mui/icons-material/Save";
import { apiUrl } from "../dataProvider";

interface LLMConfig {
  model: string;
  api_key: string;
  base_url: string;
  max_tokens: number;
  temperature: number;
  timeout: number;
  updated_at: string;
}

const PRESET_PROVIDERS = [
  {
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    models: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
  },
  {
    label: "通义千问（阿里云）",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: ["qwen-turbo", "qwen-plus", "qwen-max"],
  },
  {
    label: "豆包（字节跳动）",
    base_url: "https://ark.cn-beijing.volces.com/api/v3",
    models: ["doubao-pro-4k", "doubao-pro-32k"],
  },
];

export default function LLMConfig() {
  const [config, setConfig] = useState<LLMConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const notify = useNotify();

  useEffect(() => {
    fetch(`${apiUrl}/llm-config`)
      .then((r) => r.json())
      .then((data) => {
        setConfig(data);
        setLoading(false);
      })
      .catch(() => {
        notify("加载 LLM 配置失败", { type: "error" });
        setLoading(false);
      });
  }, [notify]);

  const handleProviderChange = (baseUrl: string) => {
    const provider = PRESET_PROVIDERS.find((p) => p.base_url === baseUrl);
    if (provider && config) {
      setConfig({
        ...config,
        base_url: baseUrl,
        model: provider.models[0],
      });
    }
  };

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      const res = await fetch(`${apiUrl}/llm-config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: config.model,
          api_key: config.api_key,
          base_url: config.base_url,
          max_tokens: config.max_tokens,
          temperature: config.temperature,
          timeout: config.timeout,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const updated = await res.json();
      setConfig(updated);
      notify("LLM 配置已保存", { type: "success" });
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

  const currentProvider = PRESET_PROVIDERS.find(
    (p) => p.base_url === config.base_url
  );

  return (
    <Box p={3} maxWidth={760}>
      <Title title="LLM 配置" />
      <Typography variant="h5" fontWeight="bold" mb={3}>
        LLM 推理配置
      </Typography>

      <Card elevation={2}>
        <CardHeader
          title="云端模型"
          subheader={
            config.updated_at
              ? `上次更新：${config.updated_at}`
              : "尚未配置"
          }
        />
        <CardContent>
          <Box display="flex" flexDirection="column" gap={3}>
            {/* 供应商预设 */}
            <FormControl fullWidth>
              <InputLabel>API 供应商（预设）</InputLabel>
              <Select
                value={config.base_url}
                label="API 供应商（预设）"
                onChange={(e) => handleProviderChange(e.target.value)}
              >
                {PRESET_PROVIDERS.map((p) => (
                  <MenuItem key={p.base_url} value={p.base_url}>
                    {p.label}
                  </MenuItem>
                ))}
                <MenuItem value={config.base_url}>
                  {!currentProvider ? `自定义（${config.base_url}）` : ""}
                </MenuItem>
              </Select>
            </FormControl>

            {/* Base URL */}
            <TextField
              label="API Base URL"
              value={config.base_url}
              onChange={(e) =>
                setConfig({ ...config, base_url: e.target.value })
              }
              fullWidth
              helperText="OpenAI 兼容接口地址"
            />

            {/* 模型名 */}
            {currentProvider ? (
              <FormControl fullWidth>
                <InputLabel>模型</InputLabel>
                <Select
                  value={config.model}
                  label="模型"
                  onChange={(e) =>
                    setConfig({ ...config, model: e.target.value })
                  }
                >
                  {currentProvider.models.map((m) => (
                    <MenuItem key={m} value={m}>
                      {m}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            ) : (
              <TextField
                label="模型名称"
                value={config.model}
                onChange={(e) =>
                  setConfig({ ...config, model: e.target.value })
                }
                fullWidth
              />
            )}

            {/* API Key */}
            <TextField
              label="API Key"
              value={config.api_key}
              onChange={(e) =>
                setConfig({ ...config, api_key: e.target.value })
              }
              type="password"
              fullWidth
              helperText="填写后保存，不显示明文"
            />

            {/* Temperature */}
            <Box>
              <Typography gutterBottom>
                Temperature（采样温度）：{config.temperature}
              </Typography>
              <Slider
                value={config.temperature}
                min={0}
                max={2}
                step={0.05}
                marks={[
                  { value: 0, label: "0" },
                  { value: 0.3, label: "0.3" },
                  { value: 1, label: "1" },
                  { value: 2, label: "2" },
                ]}
                onChange={(_, v) =>
                  setConfig({ ...config, temperature: v as number })
                }
              />
            </Box>

            {/* Max tokens */}
            <TextField
              label="Max Tokens"
              type="number"
              value={config.max_tokens}
              onChange={(e) =>
                setConfig({ ...config, max_tokens: parseInt(e.target.value) })
              }
              inputProps={{ min: 1, max: 32768 }}
              fullWidth
            />

            {/* Timeout */}
            <TextField
              label="超时秒数（超时转人工）"
              type="number"
              value={config.timeout}
              onChange={(e) =>
                setConfig({ ...config, timeout: parseFloat(e.target.value) })
              }
              inputProps={{ min: 1, max: 60, step: 0.5 }}
              fullWidth
            />

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
