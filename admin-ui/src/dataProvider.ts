/**
 * 自定义 DataProvider，适配 CS-Agent 管理后台 API。
 */

import type { DataProvider, GetListResult } from "react-admin";

const API_URL = import.meta.env.VITE_API_URL || "/api";

export const apiUrl = API_URL;

const dataProvider: DataProvider = {
  getList: async (resource, _params): Promise<GetListResult> => {
    const res = await fetch(`${API_URL}/${resource}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const records = Array.isArray(data)
      ? data.map((r: Record<string, unknown>) => ({ ...r, id: r.shop_id ?? r.id }))
      : [];
    return { data: records, total: records.length };
  },

  getOne: async (resource, params) => {
    const res = await fetch(`${API_URL}/${resource}/${params.id}`);
    if (!res.ok) throw new Error(await res.text());
    const r = await res.json();
    return { data: { ...r, id: r.shop_id ?? r.id } };
  },

  getMany: async (resource, params) => {
    const results = await Promise.all(
      params.ids.map((id) =>
        fetch(`${API_URL}/${resource}/${id}`).then((r) => r.json())
      )
    );
    return { data: results.map((r) => ({ ...r, id: r.shop_id ?? r.id })) };
  },

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  getManyReference: async (resource, params): Promise<any> => {
    const res = await fetch(`${API_URL}/${resource}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const records = (Array.isArray(data) ? data : [])
      .filter((r: Record<string, unknown>) => r[params.target] === params.id)
      .map((r: Record<string, unknown>) => ({ ...r, id: r.shop_id ?? r.id }));
    return { data: records, total: records.length };
  },

  create: async (resource, params) => {
    const res = await fetch(`${API_URL}/${resource}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params.data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    const r = await res.json();
    return { data: { ...r, id: r.shop_id ?? r.id } };
  },

  update: async (resource, params) => {
    const res = await fetch(`${API_URL}/${resource}/${params.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params.data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    const r = await res.json();
    return { data: { ...r, id: r.shop_id ?? r.id } };
  },

  updateMany: async () => ({ data: [] }),

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete: async (resource, params): Promise<any> => {
    const res = await fetch(`${API_URL}/${resource}/${params.id}`, {
      method: "DELETE",
    });
    if (!res.ok && res.status !== 204) throw new Error(await res.text());
    return { data: { id: params.id } };
  },

  deleteMany: async (resource, params) => {
    await Promise.all(
      params.ids.map((id) =>
        fetch(`${API_URL}/${resource}/${id}`, { method: "DELETE" })
      )
    );
    return { data: params.ids };
  },
};

export default dataProvider;
