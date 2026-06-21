"""
全模块共享锁池。
uid_lock：per-uid asyncio.Lock，用于同 uid 的读-改-写操作。
global_lock：全局命名锁，用于跨 uid 共享文件（如 mood_state）。
注意：defaultdict 在 asyncio 单线程事件循环里安全。
"""
import asyncio
from collections import defaultdict

_uid_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_global_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def uid_lock(uid: str) -> asyncio.Lock:
    return _uid_locks[uid]


def global_lock(name: str) -> asyncio.Lock:
    return _global_locks[name]


def locked_uids() -> list[str]:
    """Return list of uids whose uid_lock is currently held."""
    return [uid for uid, lock in _uid_locks.items() if lock.locked()]


def locked_globals() -> list[str]:
    """Return list of global lock names currently held."""
    return [name for name, lock in _global_locks.items() if lock.locked()]
