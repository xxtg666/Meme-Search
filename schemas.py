from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime


class MemeAnalysis(BaseModel):
    text_content: str = ""
    description: str
    tags: List[str] = Field(min_items=5, max_items=15)
    title: str = Field(max_length=30)

    @field_validator('description')
    def description_not_empty(cls, v):
        if not v.strip():
            raise ValueError('描述不能为空')
        return v

    @field_validator('title')
    def title_not_empty(cls, v):
        if not v.strip():
            raise ValueError('标题不能为空')
        return v


class RemoteFetchRequest(BaseModel):
    image_urls: List[str] = Field(description="图片直链列表")


class MemeResponse(BaseModel):
    id: int
    filename: str
    filepath: str
    text_content: str
    description: str
    tags: List[str]
    title: str
    upload_time: datetime
    discord_url: Optional[str] = None
    analysis_status: Optional[str] = None


class SearchResponse(BaseModel):
    total: int
    items: List[MemeResponse]
    has_more: bool
