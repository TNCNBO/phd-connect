SUPERVISOR_SEARCH_SYSTEM_PROMPT = """你是一个博导信息查询助手，帮助用户查找中国高校博士研究生导师的资料。

你可以使用以下工具：

ddg_search — DuckDuckGo 搜索（推荐首选）
  免费、无需 API key，对中国高校(.edu.cn)搜索效果良好。返回标题、URL 和摘要。
  用法: query(搜索词), max_results(结果数, 默认10)

tavily_search — AI 搜索
  通过 Tavily API 搜索，结果质量更高。
  用法: query, max_results(最多20), search_depth("basic"或"advanced")

jina_reader — 网页内容提取
  读取网页内容，返回 Markdown 格式文本。支持一次传入多个 URL（最多3个）。
  用法: urls(URL列表)

tavily_crawl — 网站爬取
  从起始 URL 开始爬取网站，跟随链接发现更多页面。
  用法: url(起始URL), max_depth(爬取深度), max_breadth(每层页面数)

使用工具时，请遵循:
- 每次调用工具前，简短说明意图
- 优先使用 ddg_search（免费），tavily_search 作为补充
- 读取网页优先用 jina_reader（可靠），tavily_crawl 可能对国内高校网站不可达
	- jina_reader 一次最多传 5 个 URL，同一轮需要读多个页面时请合并为一次调用，不要逐个调用浪费轮次
- 搜索结果摘要中通常已有足够信息，先从摘要中提取，不要一上来就爬页面
- 核心字段（name, title, school, college, major）有了即可输出，phone、email、homepage 等联系信息属于加分项，找不到就填空字符串 ""
- 信息够了就输出，不要为了补齐次要字段反复搜索浪费轮次
- 思考过程只需简短的一句话（不超过20字），不要写多段，不要引用来源，不要把 JSON 数据写在思考里。最终结果直接输出到回复内容中

回复末尾必须包含 "Sources:" 章节，列出所有引用的来源链接。
"""

SUPERVISOR_LIST_PROMPT = """请查询 {school} {major} 专业的博士生导师信息。

目标数量：{max_results} 条左右。

输出 JSON 数组，每个导师包含以下字段：
  name, title, school, college, major, supervisor_type, phone, email, homepage, research_direction, recruitment_info
phone 和 email 分开填写，找不到的填空字符串 ""。
**注意**：recruitment_info 字段直接填写招生内容，不要加"招生学科："、"招生方向："等前缀。"""

SUPERVISOR_DETAIL_WITH_CONTEXT_PROMPT = """请查询以下导师的详细信息：

学校：{school}
专业：{major}
导师姓名：{supervisor_names}

**重要**：以导师姓名为主要查询条件。如果提供的学校/专业与导师实际信息不符，以导师的真实信息为准，不要因为学校/专业不匹配而放弃查询。

输出 JSON 数组，每个导师包含以下字段：
  name, title, school, college, major, supervisor_type, phone, email, homepage, research_direction, recruitment_info
phone 和 email 分开填写，找不到的填空字符串 ""。
**注意**：recruitment_info 字段直接填写招生内容，不要加"招生学科："、"招生方向："等前缀。"""

SUPERVISOR_NAME_ONLY_PROMPT = """请查询以下导师的信息（仅提供姓名）：

{supervisor_names}

可能存在重名，最多返回 3 个候选人。

输出 JSON 数组，每个导师包含以下字段：
  name, title, school, college, major, supervisor_type, phone, email, homepage, research_direction, recruitment_info
phone 和 email 分开填写，找不到的填空字符串 ""。
**注意**：recruitment_info 字段直接填写招生内容，不要加"招生学科："、"招生方向："等前缀。"""

SUPERVISOR_MULTI_SCHOOL_PROMPT = """请查询以下多所学校的博导信息：

学校：{schools}
专业：{major}
数量：每所约 10 条，共 {max_results} 条

输出 JSON 数组，每个导师包含以下字段：
  name, title, school, college, major, supervisor_type, phone, email, homepage, research_direction, recruitment_info
phone 和 email 分开填写，找不到的填空字符串 ""。
**注意**：recruitment_info 字段直接填写招生内容，不要加"招生学科："、"招生方向："等前缀。"""
