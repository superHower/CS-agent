import {
  BooleanField,
  ChipField,
  CreateButton,
  Datagrid,
  List,
  NumberField,
  TextField,
  TopToolbar,
  EditButton,
  DeleteButton,
} from "react-admin";

const ListActions = () => (
  <TopToolbar>
    <CreateButton label="新增店铺" />
  </TopToolbar>
);

export default function ShopList() {
  return (
    <List
      actions={<ListActions />}
      title="店铺管理"
      sort={{ field: "shop_id", order: "ASC" }}
    >
      <Datagrid bulkActionButtons={false} rowClick="edit">
        <TextField source="shop_id" label="店铺 ID" />
        <ChipField source="platform" label="平台" />
        <TextField source="name" label="店铺名称" />
        <TextField source="obsidian_vault" label="知识库路径" />
        <NumberField source="confidence_threshold" label="置信度阈值" />
        <BooleanField source="enabled" label="启用" />
        <EditButton label="编辑" />
        <DeleteButton label="删除" mutationMode="pessimistic" />
      </Datagrid>
    </List>
  );
}
