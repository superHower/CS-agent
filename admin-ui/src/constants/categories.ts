/**
 * 分类工具函数 - 分类从后端动态获取，此文件仅保留通用工具函数
 */

export interface CategoryOption {
  id: string;
  name: string;
  description?: string;
}

/** 根据分类 ID 查找名称（需要传入分类列表） */
export function getCategoryName(categories: CategoryOption[], id: string): string {
  if (!id || id === "default") return "默认分类";
  return categories.find((c) => c.id === id)?.name ?? id;
}
