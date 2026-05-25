# syntax=docker/dockerfile:1.6

# A-Stock-Promotion — 零第三方依赖的纯 Python 服务
# 直接基于官方 slim 镜像即可运行，无需安装额外的 Python 包。
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

# 仅拷贝运行所需的源代码与文档，避免把测试 / .git 带入镜像
COPY src ./src
COPY README.md LICENSE ./

# 以非 root 用户运行，符合云平台最佳实践
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

EXPOSE 8080

# 容器健康检查 —— 调用内置 /api/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url='http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/health'; \
sys.exit(0 if urllib.request.urlopen(url, timeout=3).status==200 else 1)" \
    || exit 1

CMD ["python", "-m", "a_stock_promotion.api"]
