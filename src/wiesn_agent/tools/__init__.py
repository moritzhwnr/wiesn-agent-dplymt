"""Wiesn-Agent tools — browser automation and notifications."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable


def bind_tools(tools: list[Callable], **bindings: Any) -> list[Callable]:
    """Create bound versions of tool functions with injected dependencies.

    Wraps each async tool so that ``bindings`` (e.g. ``page=..., config=...``)
    are merged into ``**kwargs`` at call time.  The wrapper preserves the
    original function's ``__name__``, ``__doc__``, and type annotations so
    that the agent framework can still discover parameters.

    Example::

        bound = bind_tools([navigate, fill_field], page=browser_page)
    """
    bound: list[Callable] = []
    for tool in tools:
        @wraps(tool)
        async def _wrapper(*args: Any, _orig: Callable = tool, **kwargs: Any) -> Any:
            kwargs.update(bindings)
            return await _orig(*args, **kwargs)
        bound.append(_wrapper)
    return bound
