import { Menu } from "react-admin";
import {
  AppstoreOutlined,
  BulbOutlined,
  CustomerServiceOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  QuestionCircleOutlined,
  RobotOutlined,
  ShopOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Divider, Typography } from "antd";

const { Text } = Typography;

function Section({ label }: { label: string }) {
  return (
    <div style={{ padding: "8px 16px 4px" }}>
      <Divider style={{ margin: "4px 0" }} />
      <Text type="secondary" style={{ fontSize: 11 }}>{label}</Text>
    </div>
  );
}

export default function CustomMenu() {
  return (
    <Menu>
      <Menu.DashboardItem leftIcon={<DashboardOutlined />} primaryText="仪表盘" />
      <Menu.Item to="/shops" primaryText="店铺管理" leftIcon={<ShopOutlined />} />

      <Section label="知识库" />
      <Menu.Item to="/faq-manage" primaryText="FAQ 管理" leftIcon={<QuestionCircleOutlined />} />
      <Menu.Item to="/product-manage" primaryText="产品管理" leftIcon={<AppstoreOutlined />} />
      <Menu.Item to="/knowledge-manage" primaryText="知识条目" leftIcon={<DatabaseOutlined />} />

      <Section label="运营配置" />

      <Section label="数据分析" />
      <Menu.Item to="/message-logs" primaryText="消息日志" leftIcon={<FileTextOutlined />} />
      <Menu.Item to="/conversation-archives" primaryText="对话归档" leftIcon={<CustomerServiceOutlined />} />

      <Section label="系统配置" />
      <Menu.Item to="/llm-config" primaryText="LLM 配置" leftIcon={<RobotOutlined />} />
      <Menu.Item to="/alert-config" primaryText="告警配置" leftIcon={<BulbOutlined />} />

      <Section label="调试工具" />
      <Menu.Item to="/message-test" primaryText="消息测试" leftIcon={<ThunderboltOutlined />} />
    </Menu>
  );
}
