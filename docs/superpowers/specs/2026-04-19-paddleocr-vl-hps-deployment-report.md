# PaddleOCR-VL-1.5 HPS 部署调试报告

**日期**: 2026-04-19
**服务器**: 192.168.0.70
**服务端口**: 5564
**部署路径**: /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps/

---

## 1. 硬件环境

| GPU | 型号 | 显存 | 占用 | 用途 |
|-----|------|------|------|------|
| GPU 0 | RTX 3090 | 24GB | 19.7GB | Qwen3-VL-30B (vLLM TP0) |
| GPU 1 | RTX 3090 | 24GB | 19.7GB | Qwen3-VL-30B (vLLM TP1) |
| GPU 2 | RTX 3090 | 24GB | 15.7GB | **PaddleOCR-VL HPS (Triton + vLLM)** |
| GPU 3 | RTX 3090 | 24GB | 10.2GB | Xinference |

**总计**: 4x RTX 3090, 96GB 显存

---

## 2. HPS 架构

```
客户端 → FastAPI Gateway (5564) → Triton Server → vLLM Server
                │                      │                │
                │  并发控制/路由       │  布局检测       │  VLM 推理
                │  Semaphore(8)       │  PP-DocLayoutV3 │  PaddleOCR-VL-1.5-0.9B
                │                     │  动态批处理      │  连续批处理
```

| 容器 | 镜像 | 端口 | GPU | 说明 |
|------|------|------|-----|------|
| paddleocr-vl-api | hps-paddleocr-vl-api | 5564→8080 | - | FastAPI 网关 |
| paddleocr-vl-tritonserver | hps-paddleocr-vl-tritonserver | 内部8001 | GPU 2 | Triton 推理服务器 |
| paddleocr-vlm-server | paddleocr-genai-vllm-server | 内部8080 | GPU 2 | VLM 推理服务 (vLLM) |

---

## 3. PaddleOCR-VL API 能力验证

### 3.1 支持的输入格式

| 格式 | 支持 | 说明 |
|------|------|------|
| JPEG/JPG | ✅ | base64 传入 |
| PNG | ✅ | base64 传入 |
| BMP | ✅ | base64 传入 |
| TIFF | ✅ | base64 传入 |
| WebP | ✅ | base64 传入 |
| PDF 直传 | ✅ | `fileType: 0`，base64 传入 |
| 多页 PDF | ✅ | 63页 PDF 测试通过 |
| 多图并发请求 | ❌ | vLLM 限制，不支持一次请求多图 |
| file:// 本地路径 | ❌ | 需服务端 `--allowed-local-media-path` |

### 3.2 支持的任务类型

| 任务 | text 字段 | 输出格式 |
|------|----------|---------|
| OCR 文字识别 | `OCR:` | Markdown 文本 |
| 表格识别 | `Table Recognition:` | `<fcel>` 标记格式 |
| 公式识别 | `Formula Recognition:` | 格式化文本 |
| 图表识别 | `Chart Recognition:` | 表格数据 |

### 3.3 产线服务 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/layout-parsing` | POST | 版面解析（OCR/表格/公式/图表） |
| `/restructure-pages` | POST | 多页结果重构 |

### 3.4 请求格式

```json
POST /layout-parsing
{
  "file": "<base64编码的图片/PDF>",
  "fileType": 0,          // 0=PDF, 1=图片
  "useLayoutDetection": true,
  "restructurePages": true,
  "mergeTables": true,
  "relevelTitles": true
}
```

### 3.5 响应格式

```json
{
  "logId": "uuid",
  "errorCode": 0,
  "result": {
    "layoutParsingResults": [
      {
        "prunedResult": { /* 结构化解析结果 */ },
        "markdown": {
          "text": "# 标题\n\n正文内容...",
          "images": { /* 内嵌图片 */ }
        }
      }
    ],
    "dataInfo": { "type": "pdf", "numPages": 63 }
  }
}
```

---

## 4. 性能测试结果

### 4.1 单请求基准

| 测试 | 文件 | 页数 | 耗时 |
|------|------|------|------|
| 图片 OCR | 19KB JPEG | 1页 | <2s |
| PDF OCR | 559KB PDF | 63页 | 36s |

### 4.2 并发测试 (3x PDF)

| 请求 | 耗时 | 说明 |
|------|------|------|
| 请求 1 | 60.0s | 排队处理 |
| 请求 2 | 84.6s | 排队处理 |
| 请求 3 | 35.9s | 第一个完成 |
| **总耗时** | **84.9s** | HPS 动态批处理 |

### 4.3 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `HPS_MAX_CONCURRENT_INFERENCE_REQUESTS` | 8 | 推理最大并发 |
| `HPS_MAX_CONCURRENT_NON_INFERENCE_REQUESTS` | 32 | 非推理最大并发 |
| `UVICORN_WORKERS` | 4 | Gateway 工作进程数 |
| Triton `max_batch_size` | 8 | 动态批处理大小 |
| vLLM `max_model_len` | 16384 | 模型最大 token 长度 |
| GPU 显存占用 | ~15.7GB / 24GB | GPU 2 |

---

## 5. 调试过程与问题记录

### 问题 1：HPS 5564 请求返回 500 Internal Server Error

**现象**: 图片 OCR 请求失败，白图成功但有内容的图片全部 500。

**根因**: `pipeline_config.yaml` 中 `server_url` 配置为 `http://192.168.0.70:5564/v1`，指向 HPS 自身的 API Gateway 端口，形成**循环调用**。Triton → VLM 调用实际打到了 Gateway 自身，返回 404。

**修复**: 将 `server_url` 改为 Docker 内部网络地址 `http://paddleocr-vlm-server:8080/v1`。

**文件位置**: `/opt/PaddleOCR/deploy/paddleocr_vl_docker/hps/paddlex_hps_PaddleOCR-VL-1.5_sdk/server/pipeline_config.yaml`

```yaml
# 修复前（错误）
server_url: http://192.168.0.70:5564/v1

# 修复后（正确）
server_url: http://paddleocr-vlm-server:8080/v1
```

### 问题 2：DEVICE_ID 默认为 0 导致 GPU 冲突

**现象**: HPS 容器和 GPU 0 上已有的 Qwen3-VL vLLM 服务冲突。

**修复**: `.env` 中设置 `DEVICE_ID=2`，使用空闲的 GPU 2。

### 问题 3：Docker 构建缓存导致配置未更新

**现象**: 修改 `pipeline_config.yaml` 后 `docker compose up` 仍使用旧配置。

**修复**: `docker compose down` → `docker rmi` 删除旧镜像 → `docker compose build --no-cache` → `docker compose up -d`。

### 问题 4：5565 产线服务图片 OCR 正常但 PDF 500

**现象**: 单独部署的产线服务 (5565) 处理图片正常，PDF 返回 500。

**原因**: 5565 产线服务为标准 Docker Compose 部署，不支持并发，PDF 处理超时。

**解决方案**: 使用 HPS 架构 (5564) 替代标准部署，支持并发和 PDF 直传。

---

## 6. 配置文件清单

| 文件 | 路径 | 说明 |
|------|------|------|
| compose.yaml | `/opt/PaddleOCR/deploy/paddleocr_vl_docker/hps/compose.yaml` | Docker Compose 编排 |
| .env | `/opt/PaddleOCR/deploy/paddleocr_vl_docker/hps/.env` | 环境变量 |
| pipeline_config.yaml | `.../paddlex_hps_PaddleOCR-VL-1.5_sdk/server/pipeline_config.yaml` | 产线配置 |
| .env (SDK) | `.../paddlex_hps_PaddleOCR-VL-1.5_sdk/server/.env` | SDK 配置 |
| gateway.Dockerfile | `.../hps/gateway.Dockerfile` | Gateway 镜像构建 |
| tritonserver.Dockerfile | `.../hps/tritonserver.Dockerfile` | Triton 镜像构建 |

---

## 7. 运维命令

```bash
# 启动
cd /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps && docker compose up -d

# 停止
cd /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps && docker compose down

# 查看日志
docker logs paddleocr-vl-api --tail 50
docker logs paddleocr-vl-tritonserver --tail 50
docker logs paddleocr-vlm-server --tail 50

# 健康检查
curl http://192.168.0.70:5564/health

# 重建镜像（修改配置后）
cd /opt/PaddleOCR/deploy/paddleocr_vl_docker/hps
docker compose down
docker rmi hps-paddleocr-vl-tritonserver
docker compose build --no-cache paddleocr-vl-tritonserver
docker compose up -d
```

---

## 8. PaddleOCR-VL 知识点总结

### 两套 API 体系

| | OpenAI 兼容 API (chat/completions) | 产线服务 API (/layout-parsing) |
|--|--|--|
| 部署方式 | vLLM/SGLang 直接部署 | Docker Compose / HPS |
| 图片输入 | URL + Base64 | URL + Base64 |
| PDF 直传 | ❌ 不支持 | ✅ 支持 |
| 多页处理 | ❌ 不支持 | ✅ 逐页 + 重构 |
| 版面检测 | ❌ 不包含 | ✅ 包含 |
| 文档预处理 | ❌ 不包含 | ✅ 方向/扭曲矫正 |
| 输出格式 | 纯文本 | 结构化 JSON + Markdown |

### HPS vs 标准部署

| | 标准部署 | HPS 部署 |
|--|--|--|
| 并发 | 一次一个请求 | 支持多请求并行 |
| 架构 | FastAPI + vLLM | Gateway + Triton + vLLM |
| 动态批处理 | 不支持 | Triton 自动批处理 |
| 适用场景 | 低并发/测试 | 生产环境 |

### GPU 显存估算

| 组件 | 显存占用 |
|------|---------|
| PP-DocLayoutV3 (布局检测) | ~1 GB |
| PaddleOCR-VL-1.5-0.9B (VLM) | ~4-5 GB (FP16) |
| vLLM 运行时 + KV Cache | ~8-10 GB |
| **合计** | **~14-16 GB** |

单卡 RTX 3090 (24GB) 足够运行完整 HPS。

---

## 9. 对 PaddleOCR Web UI 项目的影响

基于以上测试结果，项目设计需更新：

1. **OCR 服务地址**: `http://192.168.0.70:5564` (HPS 产线服务)
2. **API 端点**: `/layout-parsing` (非 `/v1/chat/completions`)
3. **PDF 处理**: 直接传 PDF，**不需要** PyMuPDF 转图片
4. **并发控制**: 后端 `Semaphore(4)`，HPS 支持 8 并发推理
5. **输出格式**: 服务直接返回 Markdown + 结构化 JSON
6. **文件预处理器**: 简化，仅需处理 Word/Excel → 图片场景
