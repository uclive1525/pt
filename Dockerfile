FROM docker.m.daocloud.io/library/python:3.12-slim

ARG APP_VERSION=0.0.0
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    DATA_DIR=/app/data \
    DOWNLOAD_DIR=/app/downloads \
    APP_VERSION=${APP_VERSION}

# 对齐 jcalendar：文泉驿常规字重（微米黑），避免 Bold/描边糊死笔画
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-microhei \
    && mkdir -p /app/fonts \
    && cp /usr/share/fonts/truetype/wqy/wqy-microhei.ttc /app/fonts/ink.ttc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY VERSION ./VERSION

RUN mkdir -p /app/data /app/downloads \
    && echo "${APP_VERSION}" > /app/VERSION

LABEL org.opencontainers.image.version="${APP_VERSION}"
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
