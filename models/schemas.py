from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


class SupervisorInfo(BaseModel):
    """导师详细信息"""
    name: str = Field(..., description="姓名")
    title: str = Field(..., description="职称（教授、博士生导师等）")
    school: str = Field(..., description="所在学校")
    college: str = Field(..., description="所属学院")
    major: str = Field(..., description="招生专业")
    supervisor_type: str = Field(default="", description="导师类型（博导/硕导等）")
    phone: str = Field(default="", description="联系电话")
    email: str = Field(default="", description="联系邮箱")
    homepage: str = Field(default="", description="个人主页链接")
    research_direction: str = Field(default="", description="研究方向")
    school_level: str = Field(default="", description="院校层次（985/211/双非）")
    recruitment_info: str = Field(default="", description="近期招生说明")


class SearchRequest(BaseModel):
    """查询请求"""
    school: Optional[str] = Field(None, description="学校名称")
    major: Optional[str] = Field(None, description="专业名称")
    supervisor_names: List[str] = Field(default_factory=list, description="导师名字列表（0-5个）")
    school_level: Optional[Literal["985", "211", "双非"]] = Field(None, description="院校层次（985/211/双非）")

    @field_validator('supervisor_names')
    @classmethod
    def validate_supervisor_names_count(cls, v):
        if len(v) > 5:
            raise ValueError('supervisor_names list cannot contain more than 5 items')
        return v


class SearchResponse(BaseModel):
    """查询响应"""
    mode: Literal["detail", "table"] = Field(..., description="输出模式：detail 或 table")
    supervisors: List[SupervisorInfo] = Field(default_factory=list, description="导师信息列表")
    total_count: int = Field(..., description="结果总数")
