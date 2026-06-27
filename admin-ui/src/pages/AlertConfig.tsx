import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import { Alert, Button, Card, Col, Form, Input, Row, Select, Space, Spin, Table, Tag, Typography } from "antd";
import { SaveOutlined, NotificationOutlined, PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import { apiUrl } from "../dataProvider";
import { useCategories } from "../hooks/useCategories";

const { Title: ATitle, Text } = Typography;

// ── 告警配置部分 ──────────────────────────────────────────────────────────────

interface AlertConfigData {
  webhook_url: string;
  updated_at: string;
}

// ── 关键词/话术部分 ────────────────────────────────────────────────────────────

interface KeywordItem { id: number; category_id: string | null; shop_id: string; keyword: string; }
interface PhraseItem { id: number; category_id: string | null; shop_id: string; phrase: string; }
type ShopOption = { shop_id: string; name: string; category_id: string };

export default function AlertConfig() {
  const notify = useNotify();
  const { categories } = useCategories();

  // 告警配置状态
  const [config, setConfig] = useState<AlertConfigData | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  // 关键词/话术状态
  const [allShops, setAllShops] = useState<ShopOption[]>([]);
  const [categoryId, setCategoryId] = useState<string>("");
  const [shopId, setShopId] = useState<string>("");
  const [keywords, setKeywords] = useState<KeywordItem[]>([]);
  const [phrases, setPhrases] = useState<PhraseItem[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [savingKw, setSavingKw] = useState(false);
  const [savingPhrase, setSavingPhrase] = useState(false);

  const shops = categoryId ? allShops.filter((s) => s.category_id === categoryId) : allShops;

  // 加载告警配置
  useEffect(() => {
    fetch(`${apiUrl}/alert-config`)
      .then((r) => r.json())
      .then((data) => { setConfig(data); form.setFieldsValue(data); setLoadingConfig(false); })
      .catch(() => { notify("加载告警配置失败", { type: "error" }); setLoadingConfig(false); });
  }, [notify, form]);

  // 加载店铺列表
  useEffect(() => {
    fetch(`${apiUrl}/shops`)
      .then((r) => r.json())
      .then((data: ShopOption[]) => { if (Array.isArray(data)) setAllShops(data); })
      .catch(() => {});
  }, []);

  // 初始化分类
  useEffect(() => {
    if (categories.length > 0 && !categoryId) {
      const firstCat = categories.find((c) => c.id !== "default");
      if (firstCat) setCategoryId(firstCat.id);
    }
  }, [categories]);

  // 加载关键词和话术
  const loadLists = () => {
    setLoadingList(true);
    const params = new URLSearchParams();
    if (categoryId) params.set("category_id", categoryId);
    if (shopId) params.set("shop_id", shopId);
    const query = params.toString();

    const kwFetch = query
      ? fetch(`${apiUrl}/escalation-keywords?${query}`)
      : fetch(`${apiUrl}/escalation-keywords`);
    const phFetch = query
      ? fetch(`${apiUrl}/decoy-phrases?${query}`)
      : fetch(`${apiUrl}/decoy-phrases`);

    Promise.all([kwFetch, phFetch])
      .then(([r1, r2]) => Promise.all([r1.json(), r2.json()]))
      .then(([kwData, phData]) => {
        setKeywords(Array.isArray(kwData) ? kwData : []);
        setPhrases(Array.isArray(phData) ? phData : []);
      })
      .catch(() => { notify("加载失败", { type: "error" }); })
      .finally(() => setLoadingList(false));
  };

  useEffect(() => { loadLists(); }, [categoryId, shopId]);

  // 保存告警配置
  const handleSaveConfig = async () => {
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

  // 添加关键词
  const handleAddKeyword = async (keyword: string) => {
    if (!keyword.trim()) return;
    setSavingKw(true);
    try {
      const body: Record<string, string> = { keyword };
      if (categoryId) body.category_id = categoryId;
      if (shopId) body.shop_id = shopId;
      const res = await fetch(`${apiUrl}/escalation-keywords`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "添加失败" }));
        throw new Error(err.detail);
      }
      notify("关键词已添加", { type: "success" });
      loadLists();
    } catch (e: unknown) {
      notify(e instanceof Error ? e.message : "添加失败", { type: "error" });
    } finally {
      setSavingKw(false);
    }
  };

  // 添加话术
  const handleAddPhrase = async (phrase: string) => {
    if (!phrase.trim()) return;
    setSavingPhrase(true);
    try {
      const body: Record<string, string> = { phrase };
      if (categoryId) body.category_id = categoryId;
      if (shopId) body.shop_id = shopId;
      const res = await fetch(`${apiUrl}/decoy-phrases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      notify("话术已添加", { type: "success" });
      loadLists();
    } catch (e: unknown) {
      notify(e instanceof Error ? e.message : "添加失败", { type: "error" });
    } finally {
      setSavingPhrase(false);
    }
  };

  // 删除关键词
  const handleDeleteKeyword = (id: number) => {
    fetch(`${apiUrl}/escalation-keywords/${id}`, { method: "DELETE" })
      .then(() => { setKeywords((prev) => prev.filter((i) => i.id !== id)); notify("已删除", { type: "success" }); })
      .catch(() => notify("删除失败", { type: "error" }));
  };

  // 删除话术
  const handleDeletePhrase = (id: number) => {
    fetch(`${apiUrl}/decoy-phrases/${id}`, { method: "DELETE" })
      .then(() => { setPhrases((prev) => prev.filter((i) => i.id !== id)); notify("已删除", { type: "success" }); })
      .catch(() => notify("删除失败", { type: "error" }));
  };

  // 根据 shop_id 查找店铺名称
  const shopName = (shopIdVal: string) => {
    if (!shopIdVal || shopIdVal === "global") return "全局";
    return allShops.find((s) => s.shop_id === shopIdVal)?.name ?? shopIdVal;
  };

  const kwColumns = [
    { title: "关键词", dataIndex: "keyword", key: "keyword", render: (v: string) => <Tag color="red">{v}</Tag> },
    { title: "店铺", key: "shop", render: (_: unknown, r: KeywordItem) => shopName(r.shop_id) },
    {
      title: "操作", key: "act", width: 60,
      render: (_: unknown, r: KeywordItem) => (
        <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeleteKeyword(r.id)} />
      ),
    },
  ];

  const phraseColumns = [
    { title: "话术内容", dataIndex: "phrase", key: "phrase" },
    { title: "店铺", key: "shop", render: (_: unknown, r: PhraseItem) => shopName(r.shop_id) },
    {
      title: "操作", key: "act", width: 60,
      render: (_: unknown, r: PhraseItem) => (
        <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDeletePhrase(r.id)} />
      ),
    },
  ];

  if (loadingConfig) return <div style={{ display: "flex", justifyContent: "center", marginTop: 48 }}><Spin size="large" /></div>;

  return (
    <div style={{ padding: 24 }}>
      <Title title="告警配置" />
      <ATitle level={4}>告警与关键词配置</ATitle>

      {/* 上：企业微信配置 */}
      <Card
        title="企业微信告警配置"
        extra={config?.updated_at ? <Text type="secondary">上次更新：{config.updated_at}</Text> : null}
        style={{ marginBottom: 24 }}
      >
        <Alert
          icon={<NotificationOutlined />}
          showIcon
          type="info"
          message="当会话触发转人工时（敏感词、低置信度、系统异常），系统将自动向企业微信群机器人发送告警通知。"
          style={{ marginBottom: 16 }}
        />
        <Form form={form} layout="vertical" initialValues={config ?? {}}>
          <Form.Item
            name="webhook_url"
            label="Webhook 地址"
            extra={<>在企业微信群中添加「群机器人」后获取 Webhook 地址。<a href="https://developer.work.weixin.qq.com/document/path/91770" target="_blank" rel="noopener"> 查看文档</a></>}
          >
            <Input placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..." />
          </Form.Item>
          {config?.webhook_url && (
            <Alert type="success" message="已配置 Webhook，转人工事件将实时推送到企业微信群。" style={{ marginBottom: 16 }} />
          )}
          <Form.Item>
            <Button type="primary" icon={<SaveOutlined />} onClick={handleSaveConfig} loading={saving}>
              保存配置
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {/* 中：筛选 + 添加区域 */}
      <Card title="关键词与话术管理" style={{ marginBottom: 24 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Select
            placeholder="选择分类"
            style={{ minWidth: 160 }}
            value={categoryId || undefined}
            onChange={(v) => { setCategoryId(v ?? ""); setShopId(""); }}
            allowClear
            options={categories.filter((c) => c.id !== "default").map((c) => ({ value: c.id, label: c.name }))}
          />
          <Select
            value={shopId || undefined}
            onChange={(v) => setShopId(v ?? "")}
            style={{ minWidth: 200 }}
            allowClear
            placeholder="全部店铺"
            options={shops.map((s) => ({ value: s.shop_id, label: s.name }))}
          />
        </Space>

        <Row gutter={16}>
          <Col span={12}>
            <Space.Compact style={{ width: "100%" }}>
              <Input
                placeholder="输入转人工关键词"
                id="kw-input"
                onPressEnter={(e) => { handleAddKeyword((e.target as HTMLInputElement).value); (e.target as HTMLInputElement).value = ""; }}
              />
              <Button type="primary" icon={<PlusOutlined />} loading={savingKw}
                onClick={() => {
                  const input = document.getElementById("kw-input") as HTMLInputElement;
                  if (input?.value) { handleAddKeyword(input.value); input.value = ""; }
                }}>
                添加关键词
              </Button>
            </Space.Compact>
          </Col>
          <Col span={12}>
            <Space.Compact style={{ width: "100%" }}>
              <Input
                placeholder="输入搪塞话术"
                id="phrase-input"
                onPressEnter={(e) => { handleAddPhrase((e.target as HTMLInputElement).value); (e.target as HTMLInputElement).value = ""; }}
              />
              <Button type="primary" icon={<PlusOutlined />} loading={savingPhrase}
                onClick={() => {
                  const input = document.getElementById("phrase-input") as HTMLInputElement;
                  if (input?.value) { handleAddPhrase(input.value); input.value = ""; }
                }}>
                添加话术
              </Button>
            </Space.Compact>
          </Col>
        </Row>
      </Card>

      {/* 下：两列表 */}
      <Row gutter={16}>
        <Col span={12}>
          <Card
            title={<><Tag color="red" style={{ marginRight: 8 }}>硬转人工关键词</Tag><Text type="secondary" style={{ fontSize: 12 }}>命中即转人工，不经 LLM</Text></>}
            extra={<Text type="secondary">{keywords.length} 条</Text>}
          >
            <Table
              dataSource={keywords}
              columns={kwColumns}
              rowKey="id"
              size="small"
              loading={loadingList}
              pagination={{ pageSize: 10 }}
              locale={{ emptyText: "暂无关键词" }}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card
            title={<><Tag color="blue" style={{ marginRight: 8 }}>搪塞话术</Tag><Text type="secondary" style={{ fontSize: 12 }}>转人工前安抚买家</Text></>}
            extra={<Text type="secondary">{phrases.length} 条</Text>}
          >
            <Table
              dataSource={phrases}
              columns={phraseColumns}
              rowKey="id"
              size="small"
              loading={loadingList}
              pagination={{ pageSize: 10 }}
              locale={{ emptyText: "暂无话术" }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
