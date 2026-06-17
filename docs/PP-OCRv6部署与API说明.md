# PP-OCRv6 部署与 API 说明

> 部署位置：`192.168.0.71`（RTX 3090，与 MinerU/RAGFlow 等服务同机）
> 服务端口：`5561`
> 模型：PP-OCRv6_medium（检测 + 识别，34.5M 参数）
> 部署日期：2026-06-17

---

## 一、概述

PP-OCRv6 是 PaddleOCR 3.x 的传统 OCR 流水线（检测器 + 识别器），与 PaddleOCR-VL-1.6（VLM）互补：

| | PaddleOCR-VL-1.6 | PP-OCRv6 |
|---|---|---|
| 架构 | VLM（0.9B）端到端 | 检测 + 识别流水线 |
| 输出 | 结构化 Markdown/JSON（表格、标题、公式） | 文字行 + 坐标 + 置信度 |
| 显存 | 20GB+ | **几百 MB** |
| 速度 | 7-15s/页 | 2-3s/图（已加载） |
| 幻觉 | 有（可能脑补） | **零幻觉（置信度 0.99+）** |
| 适用 | 文档结构化解析 | 纯文字提取、精确坐标、低延迟 |

本服务定位为**零幻觉文字提取引擎**，作为 VL-1.6 的补充（非替代）。CAD 图纸表格结构化仍走 VL-1.6。

---

## 二、部署环境前提

| 项 | 要求 | 0.71 实际 |
|---|---|---|
| GPU | NVIDIA（Compute Capability ≥ 8.0） | RTX 3090 ✅ |
| 驱动 | 支持 CUDA 13.x | 595.71.05 ✅ |
| Docker | ≥ 19.03 | 29.5.2 ✅ |
| nvidia-container-toolkit | 已安装 | ✅（`--gpus all` 可用） |
| 剩余显存 | ≥ 1GB（PP-OCRv6 极省） | 10.8GB ✅ |

> **显存说明**：PP-OCRv6-medium 常驻显存仅几百 MB，实测部署后 GPU 总占用无变化（淹没在其他服务里）。即使只剩 1-2GB 也够用。

---

## 三、部署步骤

### 1. 拉取官方 Paddle GPU 镜像

镜像已内置 paddlepaddle-gpu + CUDA + cuDNN，无需自行安装大依赖。

```bash
docker pull ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddle:3.2.2-gpu-cuda13.0-cudnn9.13
```

镜像约 17GB（含 CUDA 13 + cuDNN 9.13 + paddle 3.2.2）。

### 2. 启动容器

⚠️ **关键**：必须用 `--network host`。0.71 的 docker 默认 bridge 网络存在 DNS 解析故障（容器内无法解析 archive.ubuntu.com / pypi.org），导致 apt 和 pip 都失败。host 网络直接用宿主机网络栈，绕开此问题，且**不需要重启 docker、不影响其他容器**。

```bash
mkdir -p /opt/ppocrv6/data

docker run -d \
  --name paddleocr-gpu \
  --restart unless-stopped \
  --gpus all \
  --network host \
  -v /opt/ppocrv6/data:/workspace \
  -w /workspace \
  ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddle:3.2.2-gpu-cuda13.0-cudnn9.13 \
  bash -c "sleep infinity"
```

验证环境：

```bash
docker exec paddleocr-gpu python -c "import paddle; print(paddle.__version__, paddle.device.is_compiled_with_cuda())"
# 预期: 3.2.2 True
```

### 3. 安装 paddleocr（含 PP-OCRv6）

```bash
docker exec paddleocr-gpu pip install --no-cache-dir paddleocr==3.7.0
```

paddleocr 3.7.0 自动拉取 paddlex 3.7.1，PP-OCRv6_medium 是 OCR pipeline 的默认模型。

验证：

```bash
docker exec paddleocr-gpu python -c "import paddleocr, paddlex; print(paddleocr.__version__, paddlex.__version__)"
# 预期: 3.7.0 3.7.1
```

### 4. 安装 serving 插件

⚠️ **关键**：PaddleX 3.7 把 serving 拆成独立插件，必须单独装，否则 `paddlex --serve` 报 `The serving plugin is not available`。

```bash
docker exec paddleocr-gpu paddlex --install serving
```

### 5. 启动 serving 服务

⚠️ **关键**：pipeline 名是 `OCR`（不是 `PP-OCRv6`）。`OCR` pipeline 默认加载 PP-OCRv6_medium，传 `PP-OCRv6` 会报 `pipeline does not exist`。

```bash
# 在容器内后台启动，日志写到挂载目录便于宿主机查看
docker exec paddleocr-gpu bash -c \
  'nohup paddlex --serve --pipeline OCR --host 0.0.0.0 --port 5561 > /workspace/serving.log 2>&1 &'
```

首次启动会下载 PP-OCRv6_medium 模型权重（检测 + 识别，几十 MB），约 30 秒后 `5561` 端口就绪。日志可见 `Using official model (PP-OCRv6_medium_rec)`。

验证：

```bash
curl http://localhost:5561/health
# {"logId":"...","errorCode":0,"errorMsg":"Healthy"}
ss -tln | grep 5561   # 确认监听
```

> 模型为**懒加载**：首次请求时才加载到 GPU，之后常驻。

---

## 四、踩坑记录（部署时遇到的 4 个问题）

| 问题 | 现象 | 解决 |
|------|------|------|
| 容器 DNS 故障 | apt/pip 报 `Temporary failure resolving` | `--network host` |
| 镜像 base 无 python | nvidia/cuda:base 镜像需 apt 装 python，但 apt 失败 | 直接用 paddle 官方镜像（自带 python 3.10） |
| serving 插件缺失 | `The serving plugin is not available` | `paddlex --install serving` |
| pipeline 名错误 | `pipeline (PP-OCRv6) does not exist` | 用 `--pipeline OCR`（PP-OCRv6 是其默认模型） |

---

## 五、API 调用说明

### 接口

```
POST http://192.168.0.71:5561/ocr
Content-Type: application/json
```

### 请求参数（InferRequest）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `file` | string | ✅ | 图片/PDF 内容，支持 **base64**、**URL**、本地路径（服务端） |
| `fileType` | int | 否 | `0`=PDF，`1`=图片。不传则自动判断 |
| `useDocOrientationClassify` | bool | 否 | 文档方向分类（旋转件建议开） |
| `useDocUnwarping` | bool | 否 | 文档去畸变（扫描件/翘曲建议开） |
| `useTextlineOrientation` | bool | 否 | 文字行方向 |
| `textDetThresh` | number | 否 | 检测阈值（默认 0.3） |
| `textDetBoxThresh` | number | 否 | 框阈值 |
| `textDetUnclipRatio` | number | 否 | 框扩展比例 |
| `textRecScoreThresh` | number | 否 | 识别置信度阈值（过滤低质量结果） |

> 注意：字段名是 `file`，**不是** `image`。

### 响应结构

```jsonc
{
  "logId": "...",
  "errorCode": 0,
  "errorMsg": "Success",
  "result": {
    "ocrResults": [
      {
        "prunedResult": {
          "dt_polys": [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], ...],  // 文字框坐标（4点）
          "rec_texts": ["文字行1", "文字行2", ...],               // 识别文字（与 dt_polys 一一对应）
          "rec_scores": [0.99, 0.98, ...],                         // 置信度
          "rec_polys": [...],
          "rec_boxes": [...]
        },
        "ocrImage": "<base64 处理后图>",
        "inputImage": "<base64 原图>"
      }
      // 多页 PDF 时有多个元素
    ],
    "dataInfo": { "numPages": 1, "pages": [{"width": W, "height": H}], "type": "pdf" }
  }
}
```

### 调用示例

#### Python — 图片 URL

```python
import requests
r = requests.post('http://192.168.0.71:5561/ocr',
                  json={'file': 'https://example.com/test.png'},
                  timeout=120)
texts = r.json()['result']['ocrResults'][0]['prunedResult']['rec_texts']
print(texts)
```

#### Python — 本地 PDF（base64）

```python
import base64, requests
with open('doc.pdf', 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
r = requests.post('http://192.168.0.71:5561/ocr',
                  json={'file': b64, 'fileType': 0}, timeout=300)
pages = r.json()['result']['ocrResults']
for p in pages:
    print(p['prunedResult']['rec_texts'])
```

#### curl

```bash
# URL 方式
curl -X POST http://192.168.0.71:5561/ocr \
  -H "Content-Type: application/json" \
  -d '{"file":"https://paddle-model-ecology.bj.bcebos.com/paddlex/imgs/demo_image/general_ocr_002.png"}'
```

> base64 方式不要用 curl `-d`（命令行参数超限 `Argument list too long`），用 Python/程序发送。

### 健康检查

```bash
curl http://192.168.0.71:5561/health       # 存活
curl http://192.168.0.71:5561/openapi.json # 接口 schema
```

---

## 六、性能与显存（实测）

### 速度

| 场景 | 耗时 |
|------|------|
| 首次请求（含模型加载） | 7.1s |
| 二次请求（模型已加载） | 2.4s/图 |
| A1 大幅 PDF（4824×3424） | 75s |

### 显存

- 部署前 GPU 总占用：13318 MiB
- 部署 + 推理后：**无变化**（PP-OCRv6 常驻仅几百 MB，淹没在其他服务中）
- 剩余可用：**10.8 GB**

### 测试样本（`_input_033bdf12_003_A1 594x841.pdf`，A1 建筑图纸）

| 引擎 | 字符数 | 平均置信度 | 特点 |
|------|--------|-----------|------|
| PP-OCRv6 | 6886（513 行） | **0.991** | 零幻觉，但 CAD 标题被拆成单字 |
| VL-1.6 (1.6MP) | 7439 | — | 结构化，含表格 |
| VL-1.6 (10MP) | 5606 | — | 结构化 |

**PP-OCRv6 特点**：
- ✅ 置信度高、零幻觉、提供精确坐标
- ⚠️ CAD 矢量标题被识别为逐字单行（每字独立检测框）
- ❌ 不结构化表格/标题层级（需配 PP-StructureV3）

---

## 七、运维操作

```bash
# 查看状态
docker ps --filter name=paddleocr-gpu
curl http://localhost:5561/health

# 查看日志
cat /opt/ppocrv6/data/serving.log

# 重启 serving（模型懒加载，重启后首次请求会重新加载）
docker exec paddleocr-gpu pkill -f paddlex
docker exec paddleocr-gpu bash -c \
  'nohup paddlex --serve --pipeline OCR --host 0.0.0.0 --port 5561 > /workspace/serving.log 2>&1 &'

# 重启容器
docker restart paddleocr-gpu
# 注意：容器重启后 serving 进程不会自动起（CMD 是 sleep infinity），
#       需手动执行上面的 nohup 命令，或改为自定义启动脚本

# 进入容器
docker exec -it paddleocr-gpu bash

# 停止/删除
docker stop paddleocr-gpu && docker rm paddleocr-gpu
```

### 开机自启 serving（可选）

容器默认 CMD 是 `sleep infinity`，serving 需手动起。如需开机自启，将启动命令写入容器 CMD：

```bash
# 重新创建容器，CMD 直接跑 serving
docker run -d --name paddleocr-gpu --restart unless-stopped \
  --gpus all --network host \
  -v /opt/ppocrv6/data:/workspace \
  ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddle:3.2.2-gpu-cuda13.0-cudnn9.13 \
  paddlex --serve --pipeline OCR --host 0.0.0.0 --port 5561
```

> 注意：paddleocr 包需在镜像内持久化。当前镜像已装好，重建容器用同镜像即可保留。若重新 `docker run` 不重新 build，装的 paddleocr 会丢失——建议将容器 `docker commit` 为新镜像后再用，或写 Dockerfile 固化。

---

## 八、接入本程序（PaddleOCR-ui）说明

若要在本程序 UI 提供 PP-OCRv6 选项（高精度开关旁的引擎下拉）：

1. **后端 `ocr_client.py`**：新增 `recognize_ppocrv6(file_path)` 方法，POST 到 `http://192.168.0.71:5561/ocr`，解析 `result.ocrResults[].prunedResult.rec_texts` 拼成文本。
2. **`task_engine.py`**：按 `task.engine` 字段路由（`vl16` / `ppocrv6`）。
3. **前端**：引擎下拉选项。
4. **注意输出差异**：PP-OCRv6 输出纯文本行 + 坐标，**不生成表格 Markdown**；CAD 评分表等结构化场景仍用 VL-1.6，PP-OCRv6 适合纯文字 PDF/图片快速提取。

> 当前（本文档撰写时）本程序代码未接入 PP-OCRv6，服务已就绪待调用。
