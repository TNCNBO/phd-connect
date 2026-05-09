import random
import structlog
from PhD_Connect.models.schemas import SearchRequest, SearchResponse
from PhD_Connect.agent.supervisor import SupervisorAgent
from PhD_Connect.data.school_levels import SCHOOLS_985 as _SCHOOLS_985_SET, SCHOOLS_211 as _SCHOOLS_211_SET

logger = structlog.get_logger(__name__)

# Sorted for deterministic iteration; used for "major only" school selection
SCHOOLS_985 = sorted(_SCHOOLS_985_SET)
SCHOOLS_211 = sorted(_SCHOOLS_211_SET)
SCHOOLS_OTHER = [
    "深圳大学", "南方科技大学", "杭州电子科技大学", "西安建筑科技大学",
    "浙江工业大学", "广东工业大学", "南京邮电大学", "上海理工大学",
    "江苏大学", "燕山大学", "昆明理工大学", "福建师范大学",
]

# -------------------------------------------
# School selection helpers
# -------------------------------------------

def _seed_for_major(major: str) -> random.Random:
    """Return a deterministic RNG seeded by major name for reproducible picks."""
    return random.Random(hash(major))


def _pick_one(schools: list, rng: random.Random) -> str:
    """Pick one school from a sorted list using the given RNG."""
    return rng.choice(schools)


class SupervisorSearchService:
    """导师查询服务"""

    def __init__(self):
        self._agent = None

    async def _get_agent(self):
        if self._agent is None:
            self._agent = SupervisorAgent()
        return self._agent

    def validate(self, request: SearchRequest):
        if not request.school and not request.major and not request.supervisor_names:
            raise ValueError("请输入查询条件")
        if request.school and not request.major and not request.supervisor_names:
            raise ValueError("请输入专业信息")
        if not request.school and not request.major and not request.supervisor_names and request.school_level:
            raise ValueError("请输入专业信息")

    async def search(self, request: SearchRequest) -> SearchResponse:
        logger.info("search", school=request.school, major=request.major,
                     names=request.supervisor_names, level=request.school_level)
        self.validate(request)

        agent = await self._get_agent()

        # 有学校 → 忽略 school_level
        if request.school:
            if request.supervisor_names:
                result = await agent.search(request)
            elif request.major:
                result = await agent.search(request)
            else:
                raise ValueError("请输入专业信息")
        # 无学校，有导师 → 导师详情查询
        elif request.supervisor_names:
            result = await agent.search(request)
            # 纯姓名查询：最多3个结果
            if not request.major:
                result["supervisors"] = result["supervisors"][:3]
        # 无学校，无导师，有专业 → 多校查询（3所学校，每所10条，共30条）
        elif request.major:
            result = await self._search_major_only(request, agent)
        else:
            raise ValueError("请输入更多信息")

        return SearchResponse(
            mode=result["mode"],
            supervisors=result["supervisors"],
            total_count=len(result["supervisors"])
        )

    async def search_stream(self, request: SearchRequest):
        """流式搜索，返回 (status_text | final_response)"""
        self.validate(request)
        agent = await self._get_agent()

        # 有学校 → 忽略 school_level
        if request.school:
            if request.supervisor_names or request.major:
                async for event in agent.search_stream(request):
                    # 不再过滤学校不匹配的结果 — 以导师姓名为准
                    yield event
            else:
                raise ValueError("请输入专业信息")
        # 无学校，有导师 → 导师详情查询
        elif request.supervisor_names:
            async for event in agent.search_stream(request):
                # 纯姓名查询：最多3个结果
                if event["type"] == "result" and not request.major:
                    event["supervisors"] = event["supervisors"][:3]
                yield event
        # 无学校，无导师，有专业 → 多校查询（3所学校，每所10条，共30条）
        elif request.major:
            async for event in self._search_major_only_stream(request, agent):
                yield event
        else:
            raise ValueError("请输入更多信息")

    def _select_schools(self, major: str, school_level: str | None = None) -> list:
        """Deterministically select schools using major-name seed.

        Args:
            major: Major name for seeding
            school_level: Optional filter - "985", "211", or None (all tiers)

        Returns:
            List of 3 unique schools (1 per tier if no filter, 3 from same tier if filtered)
        """
        rng = _seed_for_major(major)

        if school_level == "985":
            # 从985列表中随机选3所不重复的学校
            selected = rng.sample(SCHOOLS_985, min(3, len(SCHOOLS_985)))
        elif school_level == "211":
            selected = rng.sample(SCHOOLS_211, min(3, len(SCHOOLS_211)))
        elif school_level == "双非":
            selected = rng.sample(SCHOOLS_OTHER, min(3, len(SCHOOLS_OTHER)))
        else:
            # No filter: pick 1 from each tier
            selected = [
                _pick_one(SCHOOLS_985, rng),
                _pick_one(SCHOOLS_211, rng),
                _pick_one(SCHOOLS_OTHER, rng),
            ]

        logger.info("select_schools", major=major, school_level=school_level, selected=selected)
        return selected

    async def _search_major_only(self, request: SearchRequest, agent: SupervisorAgent):
        selected = self._select_schools(request.major, request.school_level)

        all_supervisors = []
        for school in selected:
            sr = SearchRequest(school=school, major=request.major, supervisor_names=[])
            # 通过私有属性传递数量限制给 agent
            sr._max_results = 10
            result = await agent.search(sr)
            # 每所学校取10条（双重保险）
            all_supervisors.extend(result["supervisors"][:10])

        logger.info("search_major_only_done", major=request.major, school_level=request.school_level, total=len(all_supervisors))
        return {"mode": "table", "supervisors": all_supervisors}

    async def _search_major_only_stream(self, request: SearchRequest, agent: SupervisorAgent):
        selected = self._select_schools(request.major, request.school_level)

        # 构造一个包含3所学校的查询请求
        multi_school_request = SearchRequest(
            school=None,  # 不指定单个学校
            major=request.major,
            supervisor_names=[],
            school_level=request.school_level
        )
        # 通过私有属性传递学校列表和数量限制
        multi_school_request._schools = selected
        multi_school_request._max_results = 30  # 3所学校 x 10条

        all_supervisors = []
        async for event in agent.search_stream(multi_school_request):
            if event["type"] == "result":
                all_supervisors = event["supervisors"]
            else:
                yield event

        logger.info("search_major_only_stream_done", major=request.major, school_level=request.school_level, total=len(all_supervisors))
        yield {"type": "result", "mode": "table", "supervisors": all_supervisors}
