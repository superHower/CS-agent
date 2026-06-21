import {
  BooleanInput,
  Create,
  NumberInput,
  SelectInput,
  SimpleForm,
  TextInput,
  required,
  minValue,
  maxValue,
} from "react-admin";
import { Grid } from "@mui/material";

const PLATFORMS = [
  { id: "taobao", name: "千牛（淘宝）" },
  { id: "pinduoduo", name: "拼多多" },
  { id: "jd", name: "京东" },
  { id: "douyin", name: "抖店" },
];

export default function ShopCreate() {
  return (
    <Create title="新增店铺" redirect="list">
      <SimpleForm>
        <Grid container spacing={2} width="100%">
          <Grid size={{ xs: 12, md: 6 }}>
            <TextInput source="shop_id" label="店铺 ID" helperText="格式如 tb_lamp_001" validate={[required()]} fullWidth />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <SelectInput source="platform" label="平台" choices={PLATFORMS} validate={[required()]} fullWidth />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextInput source="name" label="店铺名称" validate={[required()]} fullWidth />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextInput source="obsidian_vault" label="知识库路径" helperText="如 data/obsidian/tb_lamp_001" fullWidth />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextInput source="api_key" label="平台 API Key" fullWidth />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextInput source="api_secret" label="平台 API Secret" type="password" fullWidth />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <NumberInput source="confidence_threshold" label="置信度阈值（%）" defaultValue={85} validate={[minValue(0), maxValue(100)]} fullWidth />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <BooleanInput source="enabled" label="启用" defaultValue={true} />
          </Grid>
        </Grid>
      </SimpleForm>
    </Create>
  );
}
