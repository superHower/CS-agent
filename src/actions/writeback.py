"""Obsidian 记忆回写模块。

将会话总结异步写入对应店铺 Obsidian Vault 的 customers/{buyer_id}.md 文件。
使用内部 asyncio.Queue 实现非阻塞写入，失败重试 3 次后降级记录错误日志。
"""

import asyncio
import logging
import re
from datetime import UTC
from pathlib import Path

from src.contracts import WritebackTask
from src.utils.sensitive import mask_sensitive

logger = logging.getLogger(__name__)

_MAX_RETRY = 3


class WritebackService:
    """异步记忆回写服务。

    独立任务队列，主回复线程调用 enqueue() 后立即返回，
    后台 worker 异步消费并写入 Obsidian 文件。
    """

    def __init__(self, vault_base_path: str | Path) -> None:
        """
        Args:
            vault_base_path: 所有店铺 Obsidian Vault 的根目录，
                             实际路径为 {vault_base_path}/{shop_id}/customers/
        """
        self._base = Path(vault_base_path)
        self._queue: asyncio.Queue[WritebackTask] = asyncio.Queue()
        self._running = False

    async def enqueue(self, task: WritebackTask) -> None:
        """投入回写任务，立即返回，不阻塞调用方。"""
        await self._queue.put(task)

    async def run(self) -> None:
        """启动后台 worker，持续消费回写队列。"""
        self._running = True
        logger.info("回写服务已启动")
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._process(task)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("回写服务已停止")
                return

    async def stop(self) -> None:
        self._running = False

    async def _process(self, task: WritebackTask) -> None:
        """处理单个回写任务，失败时重试。"""
        for attempt in range(1, _MAX_RETRY + 1):
            try:
                await asyncio.to_thread(self._write_sync, task)
                return
            except Exception as exc:
                logger.warning(
                    "回写失败（第%d次）shop=%s buyer=%s: %s",
                    attempt,
                    task.shop_id,
                    task.buyer_id,
                    exc,
                )
                if attempt < _MAX_RETRY:
                    await asyncio.sleep(2**attempt)
        logger.error(
            "回写放弃 shop=%s buyer=%s（已重试%d次）", task.shop_id, task.buyer_id, _MAX_RETRY
        )

    def _write_sync(self, task: WritebackTask) -> None:
        """同步写入 Obsidian .md 文件（在线程池中执行）。"""
        # 确定文件路径
        customers_dir = self._base / task.shop_id / "customers"
        customers_dir.mkdir(parents=True, exist_ok=True)

        # 脱敏 buyer_id（用于文件名，防止路径注入）
        safe_id = re.sub(r"[^\w\-]", "_", task.buyer_id)
        file_path = customers_dir / f"{safe_id}.md"

        # 脱敏摘要内容
        summary = mask_sensitive(task.summary)
        date_str = task.session_date.astimezone(UTC).strftime("%Y-%m-%d")
        resolution_label = "已解决" if task.resolution == "resolved" else "转人工"
        tags_str = " ".join(f"[[{t}]]" for t in task.related_tags) if task.related_tags else ""

        # 构造追加内容
        entry_lines = [f"- {summary} → {resolution_label}"]
        if task.intent_label:
            entry_lines.append(f"  - 意图：{task.intent_label}")
        if tags_str:
            entry_lines.append(f"  - 相关：{tags_str}")
        entry = "\n".join(entry_lines)

        if file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            # 找到同日期块并追加，否则追加新日期块
            date_header = f"## {date_str}"
            if date_header in existing:
                # 在该日期块下追加
                new_content = existing.rstrip() + "\n" + entry + "\n"
            else:
                new_content = existing.rstrip() + f"\n\n{date_header}\n{entry}\n"
        else:
            # 新建文件
            new_content = f"# {task.buyer_id}\n\n## {date_str}\n{entry}\n"

        file_path.write_text(new_content, encoding="utf-8")
        logger.info("回写完成 shop=%s buyer=%s", task.shop_id, task.buyer_id)
