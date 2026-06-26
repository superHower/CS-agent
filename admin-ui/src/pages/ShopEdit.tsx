import {
  BooleanInput,
  Edit,
  NumberInput,
  SelectInput,
  SimpleForm,
  TextInput,
  required,
  minValue,
  maxValue,
} from "react-admin";
import { Grid } from "@mui/material";
import { CATEGORIES } from "../constants/categories";

export default function ShopEdit() {
  return (
    <Edit title="编辑店铺" mutationMode="pessimistic">
      <SimpleForm>
        <Grid container spacing={2} width="100%">
          <Grid size={{ xs: 12, md: 6 }}>
            <TextInput source="shop_id" label="店铺 ID" disabled fullWidth />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <SelectInput
              source="category_id"
              label="所属分类"
              choices={CATEGORIES}
              fullWidth
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <TextInput source="platform" label="平台" disabled fullWidth />
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
            <NumberInput source="confidence_threshold" label="置信度阈值（%）" validate={[minValue(0), maxValue(100)]} fullWidth />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <BooleanInput source="enabled" label="启用" />
          </Grid>
        </Grid>
      </SimpleForm>
    </Edit>
  );
}
