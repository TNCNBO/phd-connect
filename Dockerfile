FROM python:3.13-slim-bookworm

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

# 中文字体，用于 PDF 导出
RUN apt-get update && apt-get install -y fonts-wqy-microhei && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    nicegui>=2.5.0 \
    langchain-deepseek>=0.1.0 \
    langchain-tavily>=0.1.0 \
    tavily-python>=0.5.0 \
    pydantic>=2.0.0 \
    python-dotenv>=1.0.0 \
    httpx>=0.27.0 \
    structlog>=24.0.0 \
    reportlab>=4.0.0 \
    openpyxl>=3.1.0 \
    ddgs>=9.14.2

COPY . .

EXPOSE 8080
CMD ["python", "main.py"]
