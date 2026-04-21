# PaddleOCR-VL HPS 多 GPU 扩展部署指南

**日期**: 2026-04-19
**服务器**: 192.168.0.70
**适用版本**: PaddleOCR-VL-1.5-0.9B + HPS 架构

---

## 1. 显存需求估算

| 组件 | 显存占用 |
|------|---------|
| PP-DocLayoutV3 (布局检测) | ~1 GB |
| PaddleOCR-VL-1.5-0.9B (VLM 模型) | ~4-5 GB (FP16) |
| vLLM 运行时 + KV Cache | ~8-10 GB |
| **单个 HPS 实例合计** | **~14-16 GB** |

**最低要求**: 单卡 16GB 显存 (推荐 24GB)
**推荐 GPU**: RTX 3090 (24GB) / RTX 4090 (24GB) / A10 (24GB) / A100 (40/80GB)

---

## 2. 当前 GPU 资源分配

| GPU | 型号 | 已占用 | 占用方 | 可用 |
|-----|------|--------|--------|------|
| GPU 0 | RTX 3090 | 19.7GB | Qwen3-VL-30B (TP0) | 4.6GB |
| GPU 1 | RTX 3090 | 19.7GB | Qwen3-VL-30B (TP1) | 4.6GB |
| GPU 2 | RTX 3090 | 15.7GB | **PaddleOCR HPS #1 (5564)** | 8.3GB |
| GPU 3 | RTX 3090 | 10.7GB | Xinference | 13.7GB |

**可扩展位置**:
- GPU 2 剩余 8.3GB → 不够再放一个 HPS
- GPU 3 剩余 13.7GB → 如果停掉 Xinference (释放 10.7GB) → 共 24.4GB → **可部署第二个 HPS**
- 如服务器新增 GPU → 直接部署新 HPS 实例

---

## 3. 单实例部署步骤 (已完成)

### 3.1 目录结构

```
/opt/PaddleOCR/deploy/paddleocr_vl_docker/hps/
├── compose.yaml                    # Docker Compose 编排
├── .env                            # 环境变量
├── gateway.Dockerfile              # Gateway 镜像
├── tritonserver.Dockerfile         # Triton 镜像
└── paddlex_hps_PaddleOCR-VL-1.5_sdk/
    └── server/
        ├── pipeline_config.yaml    # 产线配置 (关键!)
        └── model_repo/             # 布局检测模型
```

### 3.2 关键配置

**`.env`**:
```bash
DEVICE_ID=2                          # GPU 编号
HPS_MAX_CONCURRENT_INFERENCE_REQUESTS=8
HPS_MAX_CONCURRENT_NON_INFERENCE_REQUESTS=32
UVICORN_WORKERS=4
```

**`compose.yaml` 端口映射**:
```yaml
services:
  paddleocr-vl-api:
    ports:
      - "5564:8080"                  # 对外端口:内部端口
```

**`pipeline_config.yaml` (最关键的配置!)**:
```yaml
VLRecognition:
  genai_config:
    backend: vllm-server
    server_url: http://paddleocr-vlm-server:8080/v1   # Docker 内部网络!
```

### 3.3 启动命令

```bash
cd /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps
docker compose up -d
```

### 3.4 验证

```bash
# 健康检查
curl http://192.168.0.70:5564/health

# 图片 OCR 测试
curl -X POST http://192.168.0.70:5564/layout-parsing \
  -H "Content-Type: application/json" \
  -d '{"file":"<base64图片>","fileType":1,"useLayoutDetection":true}'
```

---

## 4. 多实例扩展步骤

### 4.1 概述

每个 HPS 实例需要:
- 独立的 GPU (至少 16GB 空闲显存)
- 独立的端口
- 独立的 Docker Compose 项目目录
- 独立的容器名前缀 (避免冲突)

### 4.2 复制项目目录

```bash
# 假设第一个实例在 hps/
cp -r /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps \
      /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps2
```

### 4.3 修改配置 (需要改 3 个地方)

#### 修改 1: `.env` — 改 GPU 和并发

```bash
DEVICE_ID=3                          # 改为新的 GPU 编号
HPS_MAX_CONCURRENT_INFERENCE_REQUESTS=8
HPS_MAX_CONCURRENT_NON_INFERENCE_REQUESTS=32
UVICORN_WORKERS=4
```

#### 修改 2: `compose.yaml` — 改端口和容器名

```yaml
services:
  paddleocr-vl-api:
    container_name: paddleocr02-vl-api        # 加前缀 paddleocr02
    ports:
      - "5566:8080"                            # 改端口 5566
    # ... 其余不变

  paddleocr-vl-tritonserver:
    container_name: paddleocr02-vl-tritonserver
    # ...

  paddleocr-vl-vlm-server:
    container_name: paddleocr02-vlm-server
    # ...
```

#### 修改 3: `pipeline_config.yaml` — 改 VLM 服务地址

```yaml
VLRecognition:
  genai_config:
    backend: vllm-server
    server_url: http://paddleocr02-vlm-server:8080/v1   # 对应新容器名!
```

### 4.4 构建并启动

```bash
cd /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps2

# 如果修改了 Dockerfile 或 pipeline_config，需要重建
docker compose build --no-cache paddleocr-vl-tritonserver

# 启动 (VLM 模型加载需要 3-5 分钟)
docker compose up -d
```

### 4.5 验证

```bash
# 等待 VLM 加载完成 (3-5 分钟)
docker logs paddleocr02-vlm-server --tail 5

# 看到 "Uvicorn running on http://0.0.0.0:8080" 表示就绪

# 健康检查
curl http://192.168.0.70:5566/health

# 功能测试
curl -X POST http://192.168.0.70:5566/layout-parsing \
  -H "Content-Type: application/json" \
  -d '{"file":"<base64图片>","fileType":1,"useLayoutDetection":true}'
```

### 4.6 快速参考表

| 实例 | 目录 | 端口 | GPU | 容器前缀 | VLM 地址 |
|------|------|------|-----|---------|---------|
| #1 | hps/ | 5564 | 2 | paddleocr- | paddleocr-vlm-server:8080 |
| #2 | hps2/ | 5566 | 3 | paddleocr02- | paddleocr02-vlm-server:8080 |
| #3 | hps3/ | 5568 | N | paddleocr03- | paddleocr03-vlm-server:8080 |

---

## 5. 负载均衡配置

多实例启动后，需要在前端 (PaddleOCR Web UI 后端) 做负载均衡。

### 5.1 Python 后端 Round-Robin 示例

```python
import itertools

OCR_SERVERS = [
    "http://192.168.0.70:5564",
    "http://192.168.0.70:5566",
    # "http://192.168.0.70:5568",  # 更多实例...
]
server_cycle = itertools.cycle(OCR_SERVERS)

def get_ocr_server():
    """轮询获取下一个 OCR 服务地址"""
    return next(server_cycle)
```

### 5.2 Nginx 负载均衡 (可选)

```nginx
upstream paddleocr_backend {
    server 192.168.0.70:5564;
    server 192.168.0.70:5566;
    # server 192.168.0.70:5568;
}

server {
    listen 5570;
    location / {
        proxy_pass http://paddleocr_backend;
        proxy_read_timeout 600s;    # PDF 处理需要长超时
        proxy_connect_timeout 30s;
    }
}
```

### 5.3 健康检查 + 自动剔除

```python
import requests
from datetime import datetime

class OCRLoadBalancer:
    def __init__(self, servers):
        self.servers = {s: {"alive": True, "last_check": None} for s in servers}
        self._cycle = itertools.cycle(servers)

    def check_health(self):
        """定期检查所有服务健康状态"""
        for server in self.servers:
            try:
                r = requests.get(f"{server}/health", timeout=5)
                self.servers[server]["alive"] = r.status_code == 200
            except:
                self.servers[server]["alive"] = False
            self.servers[server]["last_check"] = datetime.now()

    def get_server(self):
        """获取下一个可用的服务"""
        for _ in range(len(self.servers)):
            server = next(self._cycle)
            if self.servers[server]["alive"]:
                return server
        raise Exception("所有 OCR 服务不可用")

lb = OCRLoadBalancer(["http://192.168.0.70:5564", "http://192.168.0.70:5566"])
```

---

## 6. 踩坑记录 (重要!)

### 坑 1: pipeline_config.yaml 循环调用

**现象**: 图片 OCR 返回 500，白图能成功但有内容的图片全部失败。

**根因**: `server_url` 配置为 `http://192.168.0.70:5564/v1`，指向 HPS 自身的 Gateway 端口，Triton → VLM 调用打到了 Gateway 自身，形成循环。

**正确做法**: 使用 Docker 内部网络地址:
```yaml
# 错误!
server_url: http://192.168.0.70:5564/v1

# 正确!
server_url: http://paddleocr-vlm-server:8080/v1
```

### 坑 2: DEVICE_ID 默认为 0

**现象**: HPS 容器占用 GPU 0，和其他服务冲突。

**解决**: `.env` 中明确设置 `DEVICE_ID=2`。

### 坑 3: Docker 构建缓存

**现象**: 修改 `pipeline_config.yaml` 后 `docker compose up` 仍使用旧配置。

**解决**:
```bash
docker compose down
docker rmi <旧镜像名>
docker compose build --no-cache <服务名>
docker compose up -d
```

### 坑 4: GPU 显存不足导致 VLM 循环重启

**现象**: VLM 服务每 ~15 秒重启一次，日志报 "Engine core initialization failed"。

**根因**: GPU 显存不够 (已有其他进程占用)，VLM 加载模型失败。

**解决**:
1. `nvidia-smi` 检查目标 GPU 空闲显存
2. 确保至少 16GB 空闲
3. 必要时停掉占用 GPU 的其他服务

### 坑 5: 容器名冲突

**现象**: `docker compose up` 报 "container name already in use"。

**解决**: 先 `docker rm -f` 旧容器，或修改 `compose.yaml` 中的 `container_name`。

### 坑 6: 冷启动慢

**现象**: 首次请求需要 35+ 秒 (后续 2s)。

**根因**: Triton 首次启动需下载字体等资源。

**解决**: 部署后发一次预热请求，之后响应稳定在 ~2s。

---

## 7. 运维命令速查

```bash
# === 启动/停止 ===
# 实例 #1
cd /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps && docker compose up -d
cd /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps && docker compose down

# 实例 #2
cd /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps2 && docker compose up -d
cd /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps2 && docker compose down

# === 查看日志 ===
docker logs paddleocr-vl-api --tail 50           # Gateway 日志
docker logs paddleocr-vl-tritonserver --tail 50   # Triton 日志
docker logs paddleocr-vlm-server --tail 50        # VLM 日志

# 实例 #2 把前缀换成 paddleocr02-
docker logs paddleocr02-vl-api --tail 50
docker logs paddleocr02-vl-tritonserver --tail 50
docker logs paddleocr02-vlm-server --tail 50

# === 健康检查 ===
curl http://192.168.0.70:5564/health
curl http://192.168.0.70:5566/health

# === GPU 状态 ===
nvidia-smi --query-gpu=index,memory.used,memory.free,memory.total --format=csv
nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory,name --format=csv

# === 重建镜像 (修改配置后) ===
cd /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps
docker compose down
docker rmi hps-paddleocr-vl-tritonserver
docker compose build --no-cache paddleocr-vl-tritonserver
docker compose up -d

# === 清理 VLM 重启循环 ===
docker compose down
# 等待 10 秒确保 GPU 显存释放
sleep 10
docker compose up -d
# 等待 3-5 分钟让 VLM 加载模型
docker logs paddleocr-vlm-server -f   # 实时跟踪日志
```

---

## 8. 性能基准 (单实例 RTX 3090)

| 场景 | 耗时 | QPS |
|------|------|-----|
| 单张图片 | ~2s | 0.52 |
| 8并发图片 | ~6s | 1.38 |
| 16并发图片 | ~8s | 1.95 |
| 63页PDF | ~51s | 0.019 |
| 198页PDF (33MB) | ~308s | - |
| 持续20图片 (并发4) | ~22s | 0.91 |

**N 实例预期**: 图片 QPS 约线性增长 (2实例 ~3.5 QPS, 3实例 ~5.5 QPS)

---

## 9. 扩展检查清单

部署新实例前，逐项确认:

- [ ] 目标 GPU 空闲显存 ≥ 16GB
- [ ] 端口未占用 (ss -tlnp | grep 556X)
- [ ] `.env` 中 DEVICE_ID 正确
- [ ] `compose.yaml` 端口和容器名已改
- [ ] `pipeline_config.yaml` 中 server_url 指向新容器名
- [ ] Docker 内部网络互通 (同一 compose 自动创建)
- [ ] 启动后等 3-5 分钟 VLM 加载
- [ ] 健康检查通过
- [ ] 发送预热请求 (首次请求慢)
- [ ] 功能测试 (图片 + PDF 各发一个)
