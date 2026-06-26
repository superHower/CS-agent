import { useState, useEffect, useCallback } from "react";
import { apiUrl } from "../dataProvider";

export interface Category {
  id: string;
  name: string;
  description?: string;
}

/** 动态获取分类列表的 Hook */
export function useCategories() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadCategories = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`${apiUrl}/categories`);
      if (!res.ok) throw new Error(await res.text());
      const data: Category[] = await res.json();
      setCategories(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载分类失败");
      // 失败时使用默认选项
      setCategories([{ id: "default", name: "默认分类" }]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCategories();
  }, [loadCategories]);

  return { categories, loading, error, reload: loadCategories };
}

/** 根据分类 ID 获取名称 */
export function getCategoryNameById(categories: Category[], id: string): string {
  if (!id || id === "default") return "默认分类";
  return categories.find((c) => c.id === id)?.name ?? id;
}
