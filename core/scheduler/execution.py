"""Dry-run and future real execution helpers for scheduler proposals."""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from core.safe_write import rotate_jsonl_if_needed, safe_append_jsonl
from core.sandbox import get_paths


EXECUTE_MODE = "live"


def _forensic_rotation_params() -> tuple[int, int]:
    from core.config_loader import get_config
    cfg = get_config().get("forensic_logs", {})
    return int(cfg.get("max_size_mb", 5) * 1024 * 1024), int(cfg.get("keep", 5))


def is_live_mode() -> bool:
    return EXECUTE_MODE == "live"


def legacy_tick_should_send(*, force: bool = False) -> bool:
    return force or not is_live_mode()


@dataclass(frozen=True)
class ExecuteResult:
    trigger_name: str
    would_send_prompt: str
    would_mark: list[str] = field(default_factory=list)
    would_mark_done: list[str] = field(default_factory=list)
    topic_key: str = ""
    reads_cache_ok: bool = True
    dry_run: bool = True
    sent: bool = False


ExecuteFn = Callable[..., Awaitable[ExecuteResult]]
PromptFactory = Callable[[], str]
AfterSend = Callable[[], object]


async def execute_prompt(
    *,
    trigger_name: str,
    prompt_factory: PromptFactory,
    dry_run: bool,
    search_query: str = "",
    would_mark: list[str] | tuple[str, ...] | None = None,
    would_mark_done: list[str] | tuple[str, ...] | None = None,
    topic_key: str = "",
    reads_cache_ok: bool = True,
    after_send: Optional[AfterSend] = None,
) -> ExecuteResult:
    """Execute a scheduler prompt, or log what would happen in dry-run mode."""

    prompt = str(prompt_factory() or "")
    result = ExecuteResult(
        trigger_name=trigger_name,
        would_send_prompt=prompt,
        would_mark=list(would_mark or []),
        would_mark_done=[str(x) for x in (would_mark_done or [])],
        topic_key=str(topic_key or ""),
        reads_cache_ok=reads_cache_ok,
        dry_run=dry_run,
        sent=False,
    )

    if dry_run:
        write_execute_dryrun(result)
        return result

    from core.scheduler import loop

    sent_text = await loop._pipeline_send(prompt, search_query=search_query, trigger_name=trigger_name)
    if not sent_text:
        blocked = ExecuteResult(
            trigger_name=result.trigger_name,
            would_send_prompt=result.would_send_prompt,
            would_mark=result.would_mark,
            would_mark_done=result.would_mark_done,
            topic_key=result.topic_key,
            reads_cache_ok=result.reads_cache_ok,
            dry_run=False,
            sent=False,
        )
        write_execute_blocked(blocked)
        return blocked
    if after_send is not None:
        maybe = after_send()
        if inspect.isawaitable(maybe):
            await maybe
    for name in result.would_mark:
        loop._mark(name)
    return ExecuteResult(
        trigger_name=result.trigger_name,
        would_send_prompt=result.would_send_prompt,
        would_mark=result.would_mark,
        would_mark_done=result.would_mark_done,
        topic_key=result.topic_key,
        reads_cache_ok=result.reads_cache_ok,
        dry_run=False,
        sent=True,
    )


def write_execute_dryrun(result: ExecuteResult) -> None:
    path = get_paths().execute_dryrun_log()
    safe_append_jsonl(
        path,
        {
            "ts": time.time(),
            "trigger_name": result.trigger_name,
            "would_send_prompt": result.would_send_prompt,
            "would_mark": result.would_mark,
            "would_mark_done": result.would_mark_done,
            "topic_key": result.topic_key,
            "reads_cache_ok": result.reads_cache_ok,
        },
    )
    max_bytes, keep_n = _forensic_rotation_params()
    rotate_jsonl_if_needed(path, max_bytes=max_bytes, keep_n=keep_n)


def write_execute_blocked(result: ExecuteResult) -> None:
    """记录"本该发但 pipeline 返回空"的事实；不改任何发送/mark/重试行为。"""
    path = get_paths().execute_dryrun_log()
    safe_append_jsonl(
        path,
        {
            "ts": time.time(),
            "trigger_name": result.trigger_name,
            "reason": "sent_false",
            "would_mark": result.would_mark,
            "would_mark_done": result.would_mark_done,
            "sent": False,
            "blocked": True,
        },
    )
    max_bytes, keep_n = _forensic_rotation_params()
    rotate_jsonl_if_needed(path, max_bytes=max_bytes, keep_n=keep_n)
