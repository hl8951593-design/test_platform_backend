from __future__ import annotations

from concurrent.futures import Future

from app.core.read_response_cache import read_response_cache


def invalidate_project_list_cache(*_args, **_kwargs) -> None:
    """Invalidate every per-user project-list snapshot after project aggregate data changes."""

    read_response_cache.clear_prefix(("projects",))


def invalidate_project_list_cache_on_completion(future: Future) -> None:
    """Attach aggregate-cache invalidation to a background execution lifecycle."""

    future.add_done_callback(invalidate_project_list_cache)
