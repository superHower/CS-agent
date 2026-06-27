import {
  Admin,
  CustomRoutes,
  defaultTheme,
  Layout,
} from "react-admin";
import type { LayoutProps } from "react-admin";
import { Route } from "react-router-dom";

import dataProvider from "./dataProvider";
import Dashboard from "./pages/Dashboard";
import ShopList from "./pages/ShopList";
import ShopEdit from "./pages/ShopEdit";
import LLMConfig from "./pages/LLMConfig";
import AlertConfig from "./pages/AlertConfig";
import MessageTest from "./pages/MessageTest";

import FaqManage from "./pages/FaqManage";
import ProductManage from "./pages/ProductManage";
import KnowledgeManage from "./pages/KnowledgeManage";
import CustomMenu from "./components/CustomMenu";

const theme = {
  ...defaultTheme,
  palette: {
    ...defaultTheme.palette,
    primary: { main: "#1565c0" },
    secondary: { main: "#0288d1" },
  },
};

const CustomLayout = (props: LayoutProps) => (
  <Layout {...props} menu={CustomMenu} />
);

export default function App() {
  return (
    <Admin
      dataProvider={dataProvider}
      dashboard={Dashboard}
      layout={CustomLayout}
      theme={theme}
      title="CS-Agent 管理后台"
      disableTelemetry
    >
      <CustomRoutes>
        <Route path="/shops" element={<ShopList />} />
        <Route path="/shops/:id/edit" element={<ShopEdit />} />
        <Route path="/faq-manage" element={<FaqManage />} />
        <Route path="/product-manage" element={<ProductManage />} />
        <Route path="/knowledge-manage" element={<KnowledgeManage />} />
        <Route path="/escalation-keywords" element={<AlertConfig />} />
        <Route path="/decoy-phrases" element={<AlertConfig />} />
        <Route path="/llm-config" element={<LLMConfig />} />
        <Route path="/alert-config" element={<AlertConfig />} />
        <Route path="/message-test" element={<MessageTest />} />
      </CustomRoutes>
    </Admin>
  );
}
