import {
  Admin,
  CustomRoutes,
  Resource,
  defaultTheme,
  Layout,
} from "react-admin";
import type { LayoutProps } from "react-admin";
import { Route } from "react-router-dom";
import StorefrontIcon from "@mui/icons-material/Storefront";

import dataProvider from "./dataProvider";
import Dashboard from "./pages/Dashboard";
import ShopList from "./pages/ShopList";
import ShopCreate from "./pages/ShopCreate";
import ShopEdit from "./pages/ShopEdit";
import LLMConfig from "./pages/LLMConfig";
import AlertConfig from "./pages/AlertConfig";
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
      <Resource
        name="shops"
        list={ShopList}
        create={ShopCreate}
        edit={ShopEdit}
        icon={StorefrontIcon}
        options={{ label: "店铺管理" }}
      />
      <CustomRoutes>
        <Route path="/llm-config" element={<LLMConfig />} />
        <Route path="/alert-config" element={<AlertConfig />} />
      </CustomRoutes>
    </Admin>
  );
}
