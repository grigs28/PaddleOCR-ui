# PP-OCRv6 部署与 API 说明

> 部署位置：`192.168.0.71`（RTX 3090，与 MinerU/RAGFlow 等服务同机）
> 服务端口：`5561`
> 模型：PP-OCRv6_medium（检测 + 识别，34.5M 参数）
> 部署日期：2026-06-17

---

## 一、概述

PP-OCRv6 是 PaddleOCR 3.x 的传统 OCR 流水线（检测器 + 识别器），与 PaddleOCR-VL-1.6（VLM）、MinerU（VLM）互补：

| | PaddleOCR-VL-1.6 (vl16) | PP-OCRv6 (ppocrv6) | MinerU (mineru) |
|---|---|---|---|
| 架构 | VLM（0.9B）端到端 | 检测 + 识别流水线 | VLM（vlm-engine）端到端 |
| 输出 | 结构化 Markdown/JSON（表格、标题、公式） | 文字行 + 坐标 + 置信度 | md + layout.pdf + origin.pdf + json + images |
| 显存 | 20GB+ | **850MB**（GPU）/ 0（CPU） | VLM 级别 |
| 速度 | 7-15s/页 | GPU 0.3s / CPU 2s/图 | 15-75s/PDF |
| 幻觉 | 有（可能脑补） | **零幻觉（置信度 0.99+）** | 有（VLM 通病） |
| 适用 | 文档结构化解析（CAD 表格） | 纯文字精确提取、合规核查 | 文档解析（vl 竞品），结果全量保留 |
| 服务地址 | 192.168.0.70:5564 | **192.168.0.71:5561** | 192.168.0.71:5555 |

### 引擎选择（本程序 `engine` 参数）

本程序提交任务时通过 `engine` 参数选择引擎：

| 参数值 | 引擎 | 说明 |
|--------|------|------|
| `vl16` | PaddleOCR-VL-1.6 | **默认值**，文档结构化解析，受 `high_precision` 影响 |
| `ppocrv6` | PP-OCRv6 | 零幻觉文字识别，`high_precision` 对其无影响 |
| `mineru` | MinerU | VLM 文档解析，结果 ZIP 全量保留到 `result_path` |
| **空 / 不传** | **vl16** | **向下兼容**——前版本没有 `engine` 参数的调用行为不变 |

**兼容前版本调用**：

```bash
# 前版本调用（无 engine 参数）— 仍然有效，默认用 VL-1.6
curl -X POST http://host:5553/api/v1/tasks \
  -H "X-API-Key: ak_xxx" \
  -F "file=@doc.pdf" \
  -F 'output_formats=["markdown"]'

# 新版调用（选 PP-OCRv6）
curl -X POST http://host:5553/api/v1/tasks \
  -H "X-API-Key: ak_xxx" \
  -F "file=@doc.pdf" \
  -F "engine=ppocrv6" \
  -F 'output_formats=["markdown"]'

# 新版调用（选 MinerU）
curl -X POST http://host:5553/api/v1/tasks \
  -H "X-API-Key: ak_xxx" \
  -F "file=@doc.pdf" \
  -F "engine=mineru" \
  -F 'output_formats=["markdown"]'
```

**引擎路由逻辑**（`task_engine.py`）：
- `engine` 为空或不传 → 默认 `mineru`（MinerU），走 `_process_engine_task`
- `vl16` → 现有 OCR 流水线，受 `high_precision` 影响
- `ppocrv6` / `mineru` → `_process_engine_task` 独立流程（Office/CAD 先转 PDF，含多格式输出），不走 VL 逻辑

**`high_precision` 的影响范围**：仅 `vl16` 引擎生效（切换 `maxPixels` 1.6MP↔10MP）；`ppocrv6` 和 `mineru` 引擎忽略此参数。

**`output_formats` 多格式输出**：三引擎均支持 `markdown` / `json` / `txt` / `docx` 四种格式。
- `dwg` 格式仅 **vl16 引擎的 PDF 源文件** 有效（PDF→DWG 转换），与其他格式互斥
- `_process_engine_task`（ppocrv6/mineru）在 2026-06-18 补了多格式输出（`ExportService.md_to_docx / md_to_txt`）

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

## 四、踩坑记录（部署时遇到的问题）

| 问题 | 现象 | 解决 |
|------|------|------|
| 容器 DNS 故障 | apt/pip 报 `Temporary failure resolving` | `--network host` |
| 镜像 base 无 python | nvidia/cuda:base 镜像需 apt 装 python，但 apt 失败 | 直接用 paddle 官方镜像（自带 python 3.10） |
| serving 插件缺失 | `The serving plugin is not available` | `paddlex --install serving` |
| pipeline 名错误 | `pipeline (PP-OCRv6) does not exist` | 用 `--pipeline OCR`（PP-OCRv6 是其默认模型） |
| **GPU 未启用（CPU 回退）** | paddle 日志 `CUDA device not set properly, CPU by default`；`cuInit` 返回 **803 SYSTEM_DRIVER_MISMATCH**；`device_count=0` | 见下「GPU 配置（关键）」 |

### GPU 配置（关键）——否则默认 CPU 推理

paddle 3.2.2 CUDA 13 镜像自带 `/usr/local/cuda-13.0/compat/libcuda.so.1`（forward-compat 库），与宿主机内核驱动冲突，导致 `cuInit` 返回 803，paddle 回退 CPU（表现为推理极慢、CPU 满载、GPU 占用 0）。

**完整修复**（必须三步都做）：

1. **nvidia runtime**（非默认 runc）：`--runtime=nvidia --gpus all`
2. **环境变量**：`-e NVIDIA_VISIBLE_DEVICES=all -e CUDA_VISIBLE_DEVICES=0`
3. **移除冲突的 compat 库**：
   ```bash
   docker exec paddleocr-gpu mv /usr/local/cuda-13.0/compat/libcuda.so.1 /tmp/
   docker exec paddleocr-gpu ldconfig
   ```
4. 验证：`cuInit` 返回 0、`paddle.device.cuda.device_count()` ≥ 1
5. **固化**：`docker commit paddleocr-gpu paddleocr-v6:gpu`，重启用该镜像

修复前后对比（同一张图）：

| | CPU（修复前） | GPU（修复后） |
|---|---|---|
| 二次推理耗时 | ~数秒~75s（A1） | **0.33s** |
| GPU 显存 | 0 | ~850MB |
| CPU 占用 | 993%（10核） | 极低 |

正确的启动命令（固化后）：
```bash
docker run -d --name paddleocr-gpu --restart unless-stopped \
  --runtime=nvidia --gpus all \
  -e NVIDIA_VISIBLE_DEVICES=all -e CUDA_VISIBLE_DEVICES=0 \
  --network host -v /opt/ppocrv6/data:/workspace \
  paddleocr-v6:gpu \
  paddlex --serve --pipeline OCR --host 0.0.0.0 --port 5561
```

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

**已实装**（2026-06-17）：三引擎全链路已贯通，前端引擎下拉 + 后端路由 + 数据库迁移，0.19（测试）和 0.8（生产）均已部署。

### 后端路由架构

```
task_engine._process_task
├── engine=vl16（默认）      → 现有 VL OCR 流程（ocr_client.recognize_image/pdf）
├── engine=ppocrv6             → _process_engine_task → ocr_client.recognize_ppocrv6()
│                                 POST 192.168.0.71:5561/ocr  → 文字行+坐标
└── engine=mineru              → _process_engine_task → mineru_client.process_mineru()
                                  ACADxPDF式异步三步 → ZIP 全量保留
```

### 关键文件

| 层 | 文件 | 职能 |
|---|------|------|
| 前端 | `UploadArea.vue` / `upload.js` | 引擎下拉 + `engine` 状态 + `highPrecision` 开关 |
| 后端路由 | `task_engine.py` | `engine` 参数分流，非 VL 引擎走 `_process_engine_task` |
| VL-1.6 客户端 | `ocr_client.py` | 现有 `recognize_image/pdf` + 新增 `recognize_ppocrv6` |
| MinerU 客户端 | `mineru_client.py` | 新建，异步三步（队列保障→提交→轮询 path→下载 query ZIP） |
| 配置 | `config.py` | `ppocrv6_service_url` / `mineru_service_url` / `acad_service_url` |
| 模型 | `task.py` | `engine` 字段（默认 `vl16`）+ `high_precision` 字段 |

### 注意输出差异

- **VL-1.6**：结构化 Markdown/HTML（含表格、标题层级），可能有幻觉
- **PP-OCRv6**：纯文字行 + 坐标（`rec_texts` + `dt_polys`），**不生成表格 Markdown**，零幻觉
- **MinerU**：ZIP 全量保留（md + layout.pdf + origin.pdf + json + images），前端读取 `result.md`

---

## 九、ACADxPDF API 调用说明

ACADxPDF 是 CAD 图纸（DWG/DXF）转换服务，将 CAD 图纸转为 PDF + DXF 文件，供 OCR 或 DXF 文字提取使用。

**服务地址**：`ACAD_SERVICE_URL`（默认 `http://192.168.0.5:5557`）

**认证**：请求头 `x-api-key: ACAD_SERVICE_APIKEY`

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/convert` | 提交 DWG/DXF → PDF + DXF（异步） |
| `POST` | `/convert-pdf` | 提交 PDF → DWG（异步） |
| `GET` | `/task/{task_id}` | 查询任务状态（轮询用） |
| `GET` | `/pdf-task/{task_id}` | 查询 PDF→DWG 任务状态 |
| `GET` | `/download/{task_id}` | 下载 DWG→PDF 结果 ZIP |
| `GET` | `/download-pdf-zip/{task_id}` | 下载 PDF→DWG 结果 ZIP |

### 异步三步模式

本程序通过 `doc_converter.py` 调用 ACADxPDF，采用异步三步模式：

```
1. POST /convert          → 提交文件 → 返回 task_id
2. GET  /task/{task_id}   → 轮询等待 status=done（5s 间隔）
3. GET  /download/{task_id} → 下载 ZIP → 解压分类（pdf 文件 / dxf 文件）
```

**本程序对应函数**：

| 步骤 | 函数 | 位置 |
|------|------|------|
| 通用请求（带认证） | `_acad_request(client, method, path)` | `doc_converter.py:73` |
| 轮询 | `_poll_acad_task(client, task_path, task_id)` | `doc_converter.py:84` |
| 下载解压 | `_download_acad_result(task_id, download_path, output_dir)` | `doc_converter.py:121` |
| DWG 转 PDF 入口 | `_convert_dwg_via_acad(input_path, output_dir, merge)` | `doc_converter.py:152` |
| PDF 转 DWG 入口 | `convert_pdf_to_dwg(input_path, output_dir)` | `doc_converter.py:258` |

### 任务状态

| 状态 | 说明 |
|------|------|
| `done` | 转换成功（可能部分文件失败，有 `files[].success` 字段） |
| `failed` | 全部文件转换失败 |
| 其他 | 处理中，继续轮询 |

### 降级方案

ACADxPDF 不可用时（服务无响应/返回非 HTTP 200），自动降级为**本地 `cad2x` 二进制**（`bin/cad2x`，3.5MB，被 `.gitignore` 排除），通过 `_convert_dwg_via_cad2x()` 调用。cad2x 功能有限（单页 PDF，无 DXF 输出），但能兜底。

### 本程序 CAD 处理流水线

```
DWG/DXF 文件
    ├── ACADxPDF（主方案）
    │     ├── POST /convert → PDF + DXF
    │     ├── DXF → extract_dxf_text()（ezdxf，100%准确，零幻觉）
    │     └── PDF → OCR（PaddleOCR-VL / PP-OCRv6 / MinerU，按 engine 选择）
    └── cad2x（降级）
          └── DWG → PDF → OCR
```
