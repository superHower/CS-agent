/** 预设店铺分类，不可编辑。 */

export interface CategoryOption {
  id: string;
  name: string;
  /** 可选，用于前端提示或快捷分类推断参考 */
  keywords?: string[];
}

/** 前端预设分类列表。分类 ID 与后端数据库 categories 表 id 对应。 */
export const CATEGORIES: CategoryOption[] = [
  { id: "default", name: "默认分类" },
  { id: "lamp", name: "灯具" },
  { id: "underwear", name: "内衣" },
  { id: "digital", name: "数码" },
  { id: "clothing", name: "服装" },
  { id: "beauty", name: "美妆" },
  { id: "food", name: "食品" },
  { id: "home", name: "家居" },
  { id: "baby", name: "母婴" },
  { id: "appliance", name: "家电" },
];

/** 快速按 ID 查找分类名称 */
export function getCategoryName(id: string): string {
  return CATEGORIES.find((c) => c.id === id)?.name ?? id;
}
