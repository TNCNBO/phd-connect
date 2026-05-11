import asyncio
import json
import os
import structlog
import httpx
from typing import Dict, List
from langchain_core.tools import tool

logger = structlog.get_logger(__name__)

# Concurrency limits — prevent overwhelming upstream APIs
_search_semaphore = asyncio.Semaphore(4)   # max 4 concurrent searches
_crawl_semaphore = asyncio.Semaphore(6)    # max 6 concurrent crawls
_reader_semaphore = asyncio.Semaphore(10)  # max 10 concurrent reader requests

# === DuckDuckGo Search (free, works from China) ===

@tool
async def ddg_search(
    query: str,
    max_results: int = 10,
    signal=None,
) -> List[Dict]:
    """
    DuckDuckGo 网页搜索（免费，无需 API key，对中国高校网站效果良好）。

    Args:
        query: 搜索词
        max_results: 最大结果数（默认 10）
        signal: Optional abort signal

    Returns:
        [{"title": ..., "url": ..., "snippet": ...}, ...]
    """
    from ddgs import DDGS

    _check_signal(signal, "ddg_search")

    try:
        def _do_search():
            return list(DDGS().text(query, max_results=max_results, backend="yandex"))
        results = await asyncio.to_thread(_do_search)
        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
        logger.info("ddg_search_ok", query=query[:40], results=len(formatted))
        return formatted
    except Exception:
        logger.error("ddg_search_failed", query=query[:40], exc_info=True)
        return []


object.__setattr__(ddg_search, "isConcurrencySafe", True)
object.__setattr__(ddg_search, "isReadOnly", True)


# === Jina AI Reader ===

async def _fetch_jina(url: str, client: httpx.AsyncClient, max_chars: int) -> dict:
    """提取单个 URL 的网页内容"""
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "Authorization": f"Bearer {os.getenv('JINA_API_KEY')}",
        "X-Return-Format": "markdown",
    }
    for attempt in range(2):
        try:
            response = await client.get(jina_url, headers=headers)
            response.raise_for_status()
            text = response.text
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars] + f"\n\n(内容已截断，原始大小: {len(response.text)} 字符)"
            return {"url": url, "content": text, "truncated": truncated}
        except Exception as e:
            if attempt == 1:
                logger.warning("jina_reader_failed", url=url[:80], error=str(e))
                return {"url": url, "content": f"提取失败: {str(e)}", "truncated": False}
            await asyncio.sleep(1.0)
    return {"url": url, "content": "提取失败", "truncated": False}


@tool
async def jina_reader(urls: list[str], signal=None) -> str:
    """
    使用 Jina AI Reader 提取网页内容。

    支持单个或多个 URL（并发提取）。返回 Markdown 格式文本，单条结果超过
    100,000 字符会自动截断。

    Requires the JINA_API_KEY environment variable to be set.

    Args:
        urls: 目标网页 URL 列表（单个 URL 也请传列表，如 ["https://example.com"]）
        signal: Optional abort signal — if aborted, the request will raise an exception

    Returns:
        JSON 格式结果：[{"url": ..., "content": ...}, ...]
    """
    MAX_RESULT_CHARS = 100_000

    _check_signal(signal, "jina_reader")

    if isinstance(urls, str):
        urls = [urls]

    async def _fetch_with_limit(u):
        async with _reader_semaphore:
            return await _fetch_jina(u, client, MAX_RESULT_CHARS)

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [_fetch_with_limit(u) for u in urls]
        results = await asyncio.gather(*tasks)

    logger.info("jina_reader_ok", urls=len(urls), total_chars=sum(len(r["content"]) for r in results))
    return json.dumps(results, ensure_ascii=False)


object.__setattr__(jina_reader, "isConcurrencySafe", True)
object.__setattr__(jina_reader, "isReadOnly", True)


# === Tavily Tools (round-robin key rotation) ===

_tavily_keys: list[str] | None = None
_key_index: int = 0
_key_lock = asyncio.Lock()


def _init_tavily_keys():
    """从环境变量加载 Tavily API key 列表"""
    global _tavily_keys
    raw = os.getenv("TAVILY_API_KEYS", "")
    _tavily_keys = [k.strip() for k in raw.split(",") if k.strip().startswith("tvly-")]
    if not _tavily_keys:
        logger.warning("tavily_no_keys")


async def _next_tavily_key() -> str:
    """轮询返回下一个 Tavily API key（async-safe）"""
    global _key_index
    async with _key_lock:
        if _tavily_keys is None:
            _init_tavily_keys()
        if not _tavily_keys:
            raise RuntimeError("No Tavily API keys configured")
        key = _tavily_keys[_key_index % len(_tavily_keys)]
        _key_index += 1
    return key


def _check_signal(signal, label: str = ""):
    """检查 abort signal，若已触发则抛出 RuntimeError"""
    if signal is not None:
        if callable(getattr(signal, "is_set", None)) and signal.is_set():
            raise RuntimeError(f"Aborted via signal: {label}")
        if getattr(signal, "aborted", False):
            raise RuntimeError(f"Aborted via signal: {label}")


@tool
async def tavily_search(
    query: str,
    max_results: int = 3,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    search_depth: str = "advanced",
    signal=None,
) -> List[Dict]:
    """
    Tavily AI-optimized web search. Returns clean, structured results ideal for
    finding supervisor profiles, faculty pages, and academic information.

    Args:
        query: Search query (be specific for best results)
        max_results: Max results (default 3, max 20)
        allowed_domains: Only include these domains (e.g. ["edu.cn"])
        blocked_domains: Exclude these domains
        search_depth: "basic" (fast) or "advanced" (comprehensive, default)
        signal: Optional abort signal

    Returns:
        [{"title": ..., "url": ..., "snippet": ..., "score": ...}, ...]
    """
    from tavily import TavilyClient

    _check_signal(signal, "tavily_search")
    api_key = await _next_tavily_key()
    client = TavilyClient(api_key=api_key)

    kwargs: dict = {"query": query, "max_results": min(max_results, 20), "search_depth": search_depth}
    if allowed_domains:
        kwargs["include_domains"] = allowed_domains
    if blocked_domains:
        kwargs["exclude_domains"] = blocked_domains

    try:
        async with _search_semaphore:
            response = await asyncio.to_thread(client.search, **kwargs)
        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "") or "",
                "score": r.get("score", 0),
            })
        logger.info("tavily_search_ok", query=query[:40], results=len(results))
        return results
    except Exception:
        logger.error("tavily_search_failed", query=query[:40], exc_info=True)
        return []


@tool
async def tavily_crawl(
    url: str,
    max_depth: int = 1,
    max_breadth: int = 5,
    instructions: str = "",
    allowed_domains: list[str] | None = None,
    signal=None,
) -> List[Dict]:
    """
    Crawl a website starting from a base URL, following links to discover pages.
    Ideal for crawling faculty directory pages that span multiple sub-pages.

    Args:
        url: Base URL to start crawling from
        max_depth: Max crawl depth (default 1, i.e. base page + 1 level of links)
        max_breadth: Max pages per depth level (default 5)
        instructions: Natural language instruction to guide crawling focus
        allowed_domains: Only follow links within these domains
        signal: Optional abort signal

    Returns:
        [{"url": ..., "title": ..., "content": ..., "raw_content": ...}, ...]
    """
    from tavily import TavilyClient

    _check_signal(signal, "tavily_crawl")
    api_key = await _next_tavily_key()
    client = TavilyClient(api_key=api_key)

    kwargs: dict = {
        "url": url,
        "max_depth": max_depth,
        "max_breadth": max_breadth,
        "extract_depth": "advanced",
        "format": "markdown",
    }
    if instructions:
        kwargs["instructions"] = instructions
    if allowed_domains:
        kwargs["include_domains"] = allowed_domains

    try:
        async with _crawl_semaphore:
            response = await asyncio.to_thread(client.crawl, **kwargs)
        results = []
        for r in response.get("results", []):
            raw = r.get("raw_content", "") or ""
            if len(raw) > 50_000:
                raw = raw[:50_000] + "\n\n(内容已截断)"
            results.append({
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "content": raw,
            })
        logger.info("tavily_crawl_ok", url=url[:60], pages=len(results))
        return results
    except Exception:
        logger.error("tavily_crawl_failed", url=url[:60], exc_info=True)
        return []


for _tool in [tavily_search, tavily_crawl]:
    object.__setattr__(_tool, "isConcurrencySafe", True)
    object.__setattr__(_tool, "isReadOnly", True)
