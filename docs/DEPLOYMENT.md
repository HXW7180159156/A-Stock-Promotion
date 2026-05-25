# 云端部署指南

`A-Stock-Promotion` 是纯 Python、零第三方依赖的服务，启动后即对外提供 REST API +
内置 Web UI，默认监听 **8080** 端口。本文档给出几种主流的云端部署方式。

> 入口命令：`python -m a_stock_promotion.api`
> 监听地址：由环境变量 `HOST`（默认 `0.0.0.0`）和 `PORT`（默认 `8080`）控制
> 健康检查：`GET /api/health` → `{"status":"ok"}`

---

## 1. Docker（推荐，跨平台一致）

仓库根目录已提供 [`Dockerfile`](../Dockerfile) 与 [`.dockerignore`](../.dockerignore)。

```bash
# 构建镜像
docker build -t a-stock-promotion:latest .

# 运行容器（前台）
docker run --rm -p 8080:8080 --name a-stock-promotion a-stock-promotion:latest

# 健康检查
curl http://127.0.0.1:8080/api/health
# => {"status": "ok"}
```

可通过环境变量自定义监听端口：

```bash
docker run --rm -p 9000:9000 -e PORT=9000 a-stock-promotion:latest
```

把镜像推送到任意镜像仓库（Docker Hub / GHCR / 阿里云 ACR / 腾讯云 TCR 等）后，
即可在任何兼容 OCI 的云平台（K8s、ECS、ACI、Cloud Run、App Runner 等）拉起。

---

## 2. Render / Railway / Fly.io 等 PaaS

这些平台都支持「拉取 GitHub 仓库 → 自动识别 Dockerfile → 一键部署」。

通用步骤：

1. 在平台上新建一个 Web Service，连接到本仓库。
2. 选择 **Dockerfile** 作为构建方式（不要选 Buildpack）。
3. 平台会注入 `PORT` 环境变量，本服务已自动读取并绑定。
4. 健康检查路径填写 `/api/health`。
5. 部署完成后访问平台分配的域名即可。

> Fly.io 用户可在仓库根执行 `fly launch --dockerfile`，按提示生成 `fly.toml`。

---

## 3. Kubernetes / 容器编排

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: a-stock-promotion
spec:
  replicas: 2
  selector:
    matchLabels: { app: a-stock-promotion }
  template:
    metadata:
      labels: { app: a-stock-promotion }
    spec:
      containers:
        - name: app
          image: <your-registry>/a-stock-promotion:latest
          ports:
            - containerPort: 8080
          env:
            - name: PORT
              value: "8080"
          readinessProbe:
            httpGet: { path: /api/health, port: 8080 }
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet: { path: /api/health, port: 8080 }
            initialDelaySeconds: 15
            periodSeconds: 30
          resources:
            requests: { cpu: "100m", memory: "128Mi" }
            limits:   { cpu: "500m", memory: "512Mi" }
---
apiVersion: v1
kind: Service
metadata:
  name: a-stock-promotion
spec:
  type: ClusterIP
  selector: { app: a-stock-promotion }
  ports:
    - port: 80
      targetPort: 8080
```

再通过 Ingress / LB 暴露 `Service` 即可。

---

## 4. 直接在云主机（ECS / CVM / VPS）运行

```bash
# 1. 安装 Python 3.10+（CentOS / Ubuntu 自带或通过包管理器安装）
python3 --version

# 2. 拉取代码
git clone https://github.com/HXW7180159156/A-Stock-Promotion.git
cd A-Stock-Promotion

# 3. （可选）执行测试
python3 -m unittest discover -s tests

# 4. 后台启动服务
nohup env PYTHONPATH=src HOST=0.0.0.0 PORT=8080 \
    python3 -m a_stock_promotion.api \
    > /var/log/a-stock-promotion.log 2>&1 &
```

如果需要 `systemd` 托管，新建 `/etc/systemd/system/a-stock-promotion.service`：

```ini
[Unit]
Description=A-Stock-Promotion API
After=network.target

[Service]
WorkingDirectory=/opt/A-Stock-Promotion
Environment=PYTHONPATH=/opt/A-Stock-Promotion/src
Environment=HOST=0.0.0.0
Environment=PORT=8080
ExecStart=/usr/bin/python3 -m a_stock_promotion.api
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now a-stock-promotion
sudo systemctl status a-stock-promotion
```

---

## 5. 前置反向代理（可选）

如需 HTTPS / 自定义域名，可在前面挂 Nginx / Caddy：

```nginx
server {
    listen 443 ssl http2;
    server_name your.domain.com;

    ssl_certificate     /etc/ssl/cert.pem;
    ssl_certificate_key /etc/ssl/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 6. 验证清单

部署完成后，建议依次访问以下地址确认服务可用：

| 路径 | 说明 |
|---|---|
| `GET  /api/health` | 健康检查（返回 `{"status":"ok"}`） |
| `GET  /api/strategies` | 内置策略列表（应有 12 条） |
| `GET  /` | 移动端 Web UI |
| `GET  /desktop` | 桌面端 / 管理端 Web UI |

---

## 7. 合规与运维提示

- 内置股票池为**演示样本**，不可用于实盘。生产环境请替换为合规授权数据源（AkShare、交易所等）。
- 服务为内存态，重启后社区 / 会员 / 自定义策略数据会丢失。如需持久化，请基于
  `community.py` / `membership.py` / `admin.py` 中的仓储接口接入数据库实现。
- 建议在反向代理层启用访问日志、限流和鉴权，本服务自身不做鉴权。
