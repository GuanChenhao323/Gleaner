# 拾课服务端镜像：同一镜像通过 command 启动 gateway / core / push / broker / collector / mailsvc
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY server/pyproject.toml /app/server/pyproject.toml
RUN pip install "msgpack>=1.0" "feedparser>=6.0" "beautifulsoup4>=4.12" "lxml>=5.0" "psycopg[binary]>=3.1" "cryptography>=42" "argon2-cffi>=23.1"

COPY server/gleaner /app/server/gleaner
RUN pip install --no-deps -e /app/server

# Flutter Web 构建产物（可选，由 client 构建阶段或 CI 放入 client/build/web）
COPY client/build/web* /app/web/

RUN useradd -r -u 10001 gleaner && mkdir -p /data && chown gleaner /data
USER gleaner
ENV GLEANER_DATA_DIR=/data
EXPOSE 8080 8443 8081 8100 1883 8883 7400
ENTRYPOINT ["python", "-m", "gleaner"]
CMD ["gateway"]
