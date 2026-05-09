import asyncio
import json
import os
import re
import structlog
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from PhD_Connect.agent.tools import ddg_search, jina_reader, tavily_crawl, tavily_search
from PhD_Connect.agent.prompts import (
    SUPERVISOR_SEARCH_SYSTEM_PROMPT,
    SUPERVISOR_DETAIL_WITH_CONTEXT_PROMPT,
    SUPERVISOR_NAME_ONLY_PROMPT,
    SUPERVISOR_LIST_PROMPT,
    SUPERVISOR_MULTI_SCHOOL_PROMPT,
)
from PhD_Connect.models.schemas import SupervisorInfo
from PhD_Connect.data.school_levels import get_school_level

logger = structlog.get_logger(__name__)

MAX_TURNS = 6  # hard limit
MAX_NO_PROGRESS = 2  # 连续无进展轮数，达到后强制输出

ALL_TOOLS = [ddg_search, tavily_search, tavily_crawl, jina_reader]
TOOL_BY_NAME = {t.name: t for t in ALL_TOOLS}


def _fix_school_levels(supervisors: list) -> list:
    for s in supervisors:
        if s.school:
            s.school_level = get_school_level(s.school)
    return supervisors


def _extract_json(content: str) -> list:
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass

    patterns = [
        r'```(?:json)?\s*([\s\S]*?)```',
        r'\[[\s\S]*\]',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            try:
                data = json.loads(match)
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return [data]
            except json.JSONDecodeError:
                # Try to recover truncated JSON array
                recovered = _recover_truncated_json(match)
                if recovered:
                    return recovered
                continue

    # Last resort: try direct recovery on content
    recovered = _recover_truncated_json(content)
    if recovered:
        return recovered

    logger.warning("extract_json_no_match", preview=content[:200])
    return []


def _recover_truncated_json(text: str) -> list:
    """Recover truncated JSON array by finding the last complete object."""
    # Find the last properly closed object in what looks like a JSON array
    # Strategy: find the last "}," or "}" followed by whitespace and optional "]"
    # Then close the array manually
    stripped = text.strip()
    # Must start with '[' to be a list
    if not stripped.startswith('['):
        return None

    # Walk backwards to find the last complete object
    # Look for pattern: }, followed by optional whitespace/newline and then end/truncation
    depth = 0
    last_complete_end = -1
    in_string = False
    escape_next = False

    for i, ch in enumerate(stripped):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in '{[(':
            depth += 1
        elif ch in '}])':
            depth -= 1
            if ch == '}' and depth == 1 and i + 1 < len(stripped):
                # Check if this is followed by comma or whitespace then another entry or end
                after = stripped[i + 1:].lstrip()
                if after and after[0] in ',]':
                    last_complete_end = i

    if last_complete_end > 0:
        # Close: add ] to complete the array
        candidate = stripped[:last_complete_end + 1] + ']'
        try:
            data = json.loads(candidate)
            if isinstance(data, list) and len(data) > 0:
                logger.info("json_recovered_truncated", recovered=len(data), original_len=len(stripped))
                return data
        except json.JSONDecodeError:
            pass

    return None


def _cap_tool_result(tool_name: str, content: str) -> str:
    """裁剪工具结果，防止上下文过载（Claude Code 风格）"""
    if isinstance(content, list):
        content = json.dumps(content, ensure_ascii=False)
    if not isinstance(content, str):
        content = str(content)

    # 搜索类工具：格式化为易读的 markdown（匹配 Claude Code 风格）
    if tool_name == "ddg_search":
        try:
            results = json.loads(content)
            if isinstance(results, list):
                results = results[:10]
                lines = [f"搜索结果 ({len(results)} 条):\n"]
                for r in results:
                    snippet = r.get("snippet", "")
                    if snippet:
                        lines.append(f"- [{r.get('title', '无标题')}]({r.get('url', '')}): {snippet}")
                    else:
                        lines.append(f"- [{r.get('title', '无标题')}]({r.get('url', '')})")
                return "\n".join(lines)
        except (json.JSONDecodeError, TypeError):
            pass

    elif tool_name == "tavily_search":
        try:
            results = json.loads(content)
            if isinstance(results, list):
                results = results[:10]
                lines = [f"搜索结果 ({len(results)} 条):\n"]
                for r in results:
                    snip = (r.get("snippet") or r.get("content") or "")[:500]
                    score = r.get("score", "")
                    if snip:
                        lines.append(f"- [{r.get('title', '无标题')}]({r.get('url', '')}) [score={score}]: {snip}")
                    else:
                        lines.append(f"- [{r.get('title', '无标题')}]({r.get('url', '')})")
                return "\n".join(lines)
        except (json.JSONDecodeError, TypeError):
            pass

    elif tool_name == "tavily_crawl":
        try:
            results = json.loads(content)
            if isinstance(results, list):
                capped = []
                total_chars = 0
                for item in results:
                    if isinstance(item, dict):
                        raw_content = item.get("content", "")
                        if len(raw_content) > 30000:
                            raw_content = raw_content[:30000]
                        capped_item = {
                            "url": item.get("url", ""),
                            "title": item.get("title", ""),
                            "content": raw_content,
                        }
                        capped.append(capped_item)
                        total_chars += len(raw_content)
                        if total_chars > 150000:
                            break
                    else:
                        capped.append(item)
                return json.dumps(capped, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass

    elif tool_name == "jina_reader":
        try:
            results = json.loads(content)
            if isinstance(results, list):
                # jina_reader 返回 [{url, content, truncated}, ...]
                # 保留更多内容，总字符数限制 70000
                capped = []
                total_chars = 0
                for item in results:
                    if isinstance(item, dict):
                        item_content = item.get("content", "")
                        capped_item = {
                            "url": item.get("url", ""),
                            "content": item_content,
                            "truncated": item.get("truncated", False)
                        }
                        capped.append(capped_item)
                        total_chars += len(item_content)
                        # 总字符数超过 70000 就停止
                        if total_chars > 70000:
                            break
                    else:
                        capped.append(item)
                return json.dumps(capped, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            # 如果不是 JSON，直接截断到 70000
            if len(content) > 70000:
                return content[:70000]
        return content

    # 其他工具：通用截断
    if len(content) > 40000:
        return content[:40000] + "\n\n... [内容已截断]"

    return content


def _summarize_tool_result(tool_name: str, content: str) -> str:
    """提取工具调用摘要，用于 UI 显示"""
    if isinstance(content, list):
        content = json.dumps(content, ensure_ascii=False)
    content_str = str(content or "")

    if tool_name in ("tavily_search", "ddg_search"):
        try:
            results = json.loads(content_str)
            count = len(results)
            if count == 0:
                return "搜索无结果"
            first = results[0].get("title", "") if isinstance(results[0], dict) else str(results[0])[:50]
            return f"搜索到 {count} 条: {first[:40]}"
        except (json.JSONDecodeError, TypeError):
            return f"搜索完成 ({len(content_str)} 字符)"
    elif tool_name == "tavily_crawl":
        try:
            results = json.loads(content_str)
            return f"爬取到 {len(results)} 个页面"
        except (json.JSONDecodeError, TypeError):
            return "爬取完成"
    elif tool_name == "jina_reader":
        chars = len(content_str)
        return f"网页读取完成 ({chars} 字符)"
    else:
        return f"{tool_name} 执行完成"


def _parse_supervisors(raw_list: list) -> list:
    result = []
    for item in raw_list:
        try:
            result.append(SupervisorInfo(**item))
        except Exception as e:
            logger.warning("skip_invalid", name=item.get("name", "?"), error=str(e), item=item)
    if not result and raw_list:
        logger.error("all_items_rejected", total=len(raw_list), sample=raw_list[0] if raw_list else None)
    return _fix_school_levels(result)


class SupervisorAgent:
    """导师查询 Agent — 自实现 agent loop，匹配 Claude Code 的 maxTurns 模式"""

    def __init__(self):
        logger.info("agent_init")
        base_llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            temperature=0,
            max_tokens=16384,
            timeout=int(os.getenv("DEEPSEEK_TIMEOUT", "120")),
            extra_body={"thinking": {"type": "disabled"}},
        )
        self.llm = base_llm.bind_tools(ALL_TOOLS)
        logger.info("agent_ready")

    def _build_prompt(self, request) -> str:
        if request.supervisor_names:
            # 有导师名字 — 区分是否有学校/专业上下文
            if request.school or request.major:
                # 有上下文：精确查询
                return SUPERVISOR_DETAIL_WITH_CONTEXT_PROMPT.format(
                    school=request.school or "未指定",
                    major=request.major or "未指定",
                    supervisor_names=", ".join(request.supervisor_names),
                )
            else:
                # 纯姓名查询：广泛搜索，最多 3 个结果
                return SUPERVISOR_NAME_ONLY_PROMPT.format(
                    supervisor_names=", ".join(request.supervisor_names),
                )
        else:
            # 无导师名字 — 查询学校+专业的导师列表
            # 检查是否是多校查询
            schools = getattr(request, '_schools', None)
            if schools:
                # 多校查询：传递学校列表
                max_results = getattr(request, '_max_results', 30)
                return SUPERVISOR_MULTI_SCHOOL_PROMPT.format(
                    schools=", ".join(schools),
                    major=request.major or "未指定",
                    max_results=max_results,
                )
            else:
                # 单校查询
                max_results = getattr(request, '_max_results', "所有")
                return SUPERVISOR_LIST_PROMPT.format(
                    school=request.school or "未指定",
                    major=request.major or "未指定",
                    max_results=max_results,
                )

    # ── non-streaming ──────────────────────────────────────────

    async def search(self, request):
        mode = "detail" if request.supervisor_names else "table"
        prompt = self._build_prompt(request)
        logger.info("search_start", mode=mode, school=request.school, major=request.major)

        try:
            final_content = await self._run_loop(prompt)
            logger.info("loop_finished", content_len=len(final_content))
            raw_list = _extract_json(final_content)
            supervisors = _parse_supervisors(raw_list)
            logger.info("search_done", mode=mode, supervisor_count=len(supervisors), raw_count=len(raw_list))
            return {"mode": mode, "supervisors": supervisors}
        except Exception:
            logger.error("search_failed", exc_info=True)
            raise

    # ── streaming ──────────────────────────────────────────────

    async def search_stream(self, request):
        prompt = self._build_prompt(request)
        mode = "detail" if request.supervisor_names else "table"
        logger.info("search_stream", mode=mode, school=request.school, major=request.major)

        yield {"type": "status", "text": "AI 正在分析查询..."}

        final_content = ""
        try:
            async for event in self._run_loop_streaming(prompt):
                if event["type"] == "final":
                    final_content = event["content"]
                else:
                    yield event

            raw_list = _extract_json(final_content)

            # Partial recovery on parse failure
            if not raw_list and len(final_content) > 500:
                yield {"type": "status", "text": "正在整理结果..."}
                last_array = None
                for m in re.finditer(r'\[[\s\S]*\]', final_content):
                    last_array = m.group()
                if last_array:
                    raw_list = _extract_json(last_array)
                    if raw_list:
                        logger.info("json_recovered", count=len(raw_list))

            supervisors = _parse_supervisors(raw_list)
            logger.info("search_done", mode=mode, supervisor_count=len(supervisors), raw_count=len(raw_list))
            yield {"type": "result", "mode": mode, "supervisors": supervisors}

        except Exception as e:
            logger.error("stream_failed", exc_info=True)
            yield {"type": "error", "text": str(e)}

    # ── core agent loop (matches Claude Code query.ts pattern) ─

    @staticmethod
    def _build_progress_note(turn: int, tool_names: list[str], tool_results: list) -> str:
        """简洁的工具结果摘要，不透露剩余轮数，让 LLM 自行判断何时输出。"""

        total_search_results = 0
        total_reader_chars = 0

        for tr in tool_results:
            content = tr.content if hasattr(tr, 'content') else str(tr)
            if isinstance(content, str):
                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    if len(content) > 100:
                        total_reader_chars += len(content)
                    continue
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    keys = data[0].keys()
                    if "snippet" in keys:
                        total_search_results += len(data)
                    elif "content" in keys:
                        for item in data:
                            total_reader_chars += len(item.get("content", ""))
            elif isinstance(content, list):
                total_search_results += len(content)

        parts = []
        if total_search_results:
            parts.append(f"本轮获得 {total_search_results} 条搜索结果")
        if total_reader_chars:
            parts.append(f"读取网页 {total_reader_chars:,} 字符")

        remaining = MAX_TURNS - turn
        if parts:
            return f"[第{turn}/{MAX_TURNS}轮] {'；'.join(parts)}。剩余{remaining}轮。如果信息足够，请直接输出 JSON。"
        return f"[第{turn}/{MAX_TURNS}轮] 无新数据。剩余{remaining}轮。如果信息足够，请直接输出 JSON。"

    @staticmethod
    def _has_progress(tool_results: list) -> bool:
        """检查本轮工具调用是否产出了有效数据。"""
        for tr in tool_results:
            content = tr.content if hasattr(tr, 'content') else str(tr)
            if not content:
                continue
            if isinstance(content, str):
                try:
                    data = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    return len(content) > 200
                if isinstance(data, list) and len(data) > 0:
                    return True
                if isinstance(data, dict) and len(data) > 0:
                    return True
            elif isinstance(content, (list, dict)):
                return True
        return False

    async def _run_loop(self, user_prompt: str) -> str:
        """Non-streaming agent loop. Returns final LLM text content."""
        messages = [
            SystemMessage(content=SUPERVISOR_SEARCH_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        turn_count = 0
        no_progress_streak = 0

        while turn_count < MAX_TURNS:
            turn_count += 1
            ctx_chars = sum(len(str(m.content or "")) for m in messages)
            logger.info("turn_start", turn=turn_count, max_turns=MAX_TURNS, msg_count=len(messages), ctx_chars=ctx_chars)

            response = await self.llm.ainvoke(messages)
            messages.append(response)

            tc_names = [tc.get("name", "?") for tc in (response.tool_calls or [])]
            logger.info(
                "llm_response",
                turn=turn_count,
                has_tool_calls=bool(response.tool_calls),
                tool_count=len(tc_names),
                tools=tc_names,
                content_len=len(response.content or ""),
            )

            if not response.tool_calls:
                logger.info("loop_exit", reason="terminal", turns=turn_count)
                return response.content or ""

            # Execute tools in parallel
            async def _exec_one(tc):
                tool = TOOL_BY_NAME.get(tc["name"])
                if tool is None:
                    return ToolMessage(content="未知工具", tool_call_id=tc["id"]), tc["name"]
                try:
                    raw = await tool.ainvoke(tc["args"])
                    capped = _cap_tool_result(tc["name"], raw)
                    result_len = len(capped) if isinstance(capped, str) else len(str(capped))
                    logger.debug("tool_done", turn=turn_count, tool=tc["name"], result_len=result_len)
                    return ToolMessage(content=capped, tool_call_id=tc["id"]), tc["name"]
                except Exception as e:
                    logger.warning("tool_failed", turn=turn_count, tool=tc["name"], error=str(e))
                    return ToolMessage(content=str(e), tool_call_id=tc["id"]), tc["name"]

            gathered = await asyncio.gather(*[_exec_one(tc) for tc in response.tool_calls])
            tool_results = [r[0] for r in gathered]
            tool_names_used = [r[1] for r in gathered]

            messages.extend(tool_results)

            # No-progress detection
            if self._has_progress(tool_results):
                no_progress_streak = 0
            else:
                no_progress_streak += 1
                if no_progress_streak >= MAX_NO_PROGRESS:
                    logger.warning("loop_exit", reason="no_progress", turns=turn_count)
                    messages.append(
                        HumanMessage(content="连续多轮未获取到有效数据。请根据已有信息直接输出 JSON 结果。")
                    )
                    final = await self.llm.ainvoke(messages)
                    return final.content or ""

            # Per-turn progress injection
            note = self._build_progress_note(turn_count, tool_names_used, tool_results)
            messages.append(HumanMessage(content=note))
            logger.info("turn_end", turn=turn_count, tools_used=tool_names_used, progress_note=note)

        # max_turns hit — ask LLM to summarize
        logger.warning("loop_exit", reason="max_turns", turns=turn_count)
        messages.append(
            HumanMessage(content="已达到最大搜索轮数，不能再调用任何工具。请根据已有信息直接输出 JSON 数组，不要说[让我查看]或[下一步]，只输出 JSON。")
        )
        final = await self.llm.ainvoke(messages)
        result = final.content or ""
        # If LLM still didn't output JSON, retry once with stronger instruction
        if not _extract_json(result):
            messages.append(AIMessage(content=result))
            messages.append(
                HumanMessage(content="你的回复中没有 JSON 数组。请直接输出 JSON，以 [ 开头、] 结尾，不要输出其他文字。")
            )
            final = await self.llm.ainvoke(messages)
            result = final.content or ""
        return result

    async def _run_loop_streaming(self, user_prompt: str):
        """Streaming agent loop. Yields status/thinking/final events."""
        messages = [
            SystemMessage(content=SUPERVISOR_SEARCH_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        turn_count = 0
        final_content = ""
        no_progress_streak = 0

        while turn_count < MAX_TURNS:
            turn_count += 1
            ctx_chars = sum(len(str(m.content or "")) for m in messages)
            logger.info("turn_start", turn=turn_count, max_turns=MAX_TURNS, msg_count=len(messages), ctx_chars=ctx_chars)

            # --- LLM call ---
            response = await self.llm.ainvoke(messages)
            messages.append(response)

            tc_names = [tc.get("name", "?") for tc in (response.tool_calls or [])]
            logger.info(
                "llm_response",
                turn=turn_count,
                has_tool_calls=bool(response.tool_calls),
                tool_count=len(tc_names),
                tools=tc_names,
                content_len=len(response.content or ""),
            )

            # Show thinking (content before tool calls) — truncated to first sentence
            if response.content and isinstance(response.content, str):
                thinking = response.content.strip()
                if thinking:
                    first_line = thinking.split("\n")[0]
                    if len(first_line) > 80:
                        first_line = first_line[:80] + "..."
                    yield {"type": "thinking", "text": first_line}

            # --- No tool calls → done ---
            if not response.tool_calls:
                final_content = response.content or ""
                logger.info("loop_exit", reason="terminal", turns=turn_count)
                break

            # --- Show tool call intents ---
            for tc in response.tool_calls:
                name = tc.get("name", "")
                args = tc.get("args", {})
                if name == "ddg_search":
                    q = args.get("query", "") if isinstance(args, dict) else ""
                    yield {"type": "status", "text": f"DuckDuckGo 搜索: {q}"}
                elif name == "tavily_search":
                    q = args.get("query", "") if isinstance(args, dict) else ""
                    yield {"type": "status", "text": f"Tavily 搜索: {q}"}
                elif name == "tavily_crawl":
                    u = args.get("url", "") if isinstance(args, dict) else ""
                    yield {"type": "status", "text": f"Tavily 爬取: {u[:50]}..."}
                elif name == "jina_reader":
                    yield {"type": "status", "text": "正在读取网页..."}
                else:
                    yield {"type": "status", "text": f"执行: {name}..."}

            # --- Execute tools in parallel ---
            async def _exec_one_with_summary(tc):
                tool = TOOL_BY_NAME.get(tc["name"])
                if tool is None:
                    return ToolMessage(content="未知工具", tool_call_id=tc["id"]), tc["name"], "未知工具"
                try:
                    raw = await tool.ainvoke(tc["args"])
                    capped = _cap_tool_result(tc["name"], raw)
                    result_len = len(capped) if isinstance(capped, str) else len(str(capped))
                    logger.debug("tool_done", turn=turn_count, tool=tc["name"], result_len=result_len)
                    summary = _summarize_tool_result(tc["name"], capped)
                    return ToolMessage(content=capped, tool_call_id=tc["id"]), tc["name"], summary
                except Exception as e:
                    logger.warning("tool_failed", turn=turn_count, tool=tc["name"], error=str(e))
                    return ToolMessage(content=str(e), tool_call_id=tc["id"]), tc["name"], f"{tc['name']} 失败: {e}"

            gathered = await asyncio.gather(*[_exec_one_with_summary(tc) for tc in response.tool_calls])
            tool_results = [r[0] for r in gathered]
            tool_names_used = [r[1] for r in gathered]
            for r in gathered:
                yield {"type": "status", "text": r[2]}

            messages.extend(tool_results)

            # No-progress detection
            if self._has_progress(tool_results):
                no_progress_streak = 0
            else:
                no_progress_streak += 1
                if no_progress_streak >= MAX_NO_PROGRESS:
                    logger.warning("loop_exit", reason="no_progress", turns=turn_count)
                    yield {"type": "status", "text": "连续多轮未获取有效数据，正在整理结果..."}
                    messages.append(
                        HumanMessage(content="连续多轮未获取到有效数据。请根据已有信息直接输出 JSON 结果。")
                    )
                    final = await self.llm.ainvoke(messages)
                    final_content = final.content or ""
                    break

            # Per-turn progress injection
            note = self._build_progress_note(turn_count, tool_names_used, tool_results)
            messages.append(HumanMessage(content=note))
            logger.info("turn_end", turn=turn_count, tools_used=tool_names_used, progress_note=note)

        # If loop ended without final content (max_turns hit), force summarize
        if not final_content:
            logger.warning("loop_exit", reason="max_turns", turns=turn_count)
            yield {"type": "status", "text": "搜索已达上限，正在整理结果..."}
            messages.append(
                HumanMessage(content="已达到最大搜索轮数，不能再调用任何工具。请根据已有信息直接输出 JSON 数组，不要说[让我查看]或[下一步]，只输出 JSON。")
            )
            final = await self.llm.ainvoke(messages)
            final_content = final.content or ""
            # If LLM still didn't output JSON, retry once with stronger instruction
            if not _extract_json(final_content):
                messages.append(AIMessage(content=final_content))
                messages.append(
                    HumanMessage(content="你的回复中没有 JSON 数组。请直接输出 JSON，以 [ 开头、] 结尾，不要输出其他文字。")
                )
                final = await self.llm.ainvoke(messages)
                final_content = final.content or ""

        yield {"type": "final", "content": final_content}
