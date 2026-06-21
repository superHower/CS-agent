import { Menu } from "react-admin";
import StorefrontIcon from "@mui/icons-material/Storefront";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import NotificationsActiveIcon from "@mui/icons-material/NotificationsActive";
import SpaceDashboardIcon from "@mui/icons-material/SpaceDashboard";
import { Divider, Typography, Box } from "@mui/material";

export default function CustomMenu() {
  return (
    <Menu>
      <Menu.DashboardItem
        leftIcon={<SpaceDashboardIcon />}
        primaryText="仪表盘"
      />
      <Menu.ResourceItem name="shops" leftIcon={<StorefrontIcon />} />
      <Box mx={2} my={1}>
        <Divider />
        <Typography variant="caption" color="text.secondary" sx={{ px: 1, display: "block", mt: 1 }}>
          系统配置
        </Typography>
      </Box>
      <Menu.Item
        to="/llm-config"
        primaryText="LLM 配置"
        leftIcon={<SmartToyIcon />}
      />
      <Menu.Item
        to="/alert-config"
        primaryText="告警配置"
        leftIcon={<NotificationsActiveIcon />}
      />
    </Menu>
  );
}
