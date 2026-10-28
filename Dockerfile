# 单阶段足够：这是纯 Python 服务，没有编译产物要分层。
# 镜像里带语料（4 本合成手册 1.2 MB），运行期状态走挂载卷，见 docker-compose.yml。
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STATE_DB=/state/state.sqlite3

WORKDIR /app

# 依赖单独一层：改代码不用重装依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY core ./core
COPY domains ./domains
COPY app ./app
COPY web ./web
COPY scripts ./scripts
COPY data ./data
# 评测报告是页面指标条的数据来源，不带就只剩空面板
COPY evals ./evals

RUN mkdir -p /state

EXPOSE 8080

# 启动前先自检：语料缺失时给出"缺哪个文件"而不是让每个问题都变成拒答
CMD ["sh", "-c", "python scripts/bootstrap.py && python -m uvicorn app.main:app --host 0.0.0.0 --port 8080"]

HEALTHCHECK --interval=15s --timeout=3s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz').status==200 else 1)"
