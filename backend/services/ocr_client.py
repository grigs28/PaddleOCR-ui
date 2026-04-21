import base64
import os
import re
import aiohttp
import asyncio
import logging
from backend.config import get_settings

logger = logging.getLogger(__name__)


class OCRClient:
    """PaddleOCR-VL HPS 产线服务客户端"""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.ocr_service_url
        # base64 分片读取大小：必须是 3 的倍数，保证编码拼接无 padding
        self._b64_chunk = (settings.chunk_size // 3) * 3

    def _encode_file_b64(self, file_path: str) -> str:
        """分片读取文件并 base64 编码，避免一次性加载到内存"""
        parts = []
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(self._b64_chunk)
                if not chunk:
                    break
                parts.append(base64.b64encode(chunk).decode())
        return "".join(parts)

    async def _call_layout_parsing(
        self, file_b64: str, file_type: int, timeout: int = 600
    ) -> dict:
        """
        调用 HPS /layout-parsing 接口

        Args:
            file_b64: base64 编码的文件内容
            file_type: 0=PDF, 1=图片
            timeout: 请求超时秒数
        """
        payload = {
            "file": file_b64,
            "fileType": file_type,
            "useLayoutDetection": True,
            "restructurePages": True,
            "mergeTables": True,
            "relevelTitles": True,
        }
        async with aiohttp.ClientSession() as client:
            async with client.post(
                f"{self.base_url}/layout-parsing",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"OCR 服务返回 {resp.status}: {text[:200]}")
                return await resp.json()

    async def recognize_image(self, image_path: str) -> dict:
        """
        识别单张图片

        Returns:
            {"markdown": "识别文本", "pages": 1, "raw_response": {...}}
        """
        file_b64 = self._encode_file_b64(image_path)
        data = await self._call_layout_parsing(file_b64, file_type=1, timeout=get_settings().ocr_image_timeout)
        return self._parse_response(data)

    async def recognize_pdf(self, pdf_path: str, num_pages: int = 0) -> dict:
        """
        识别 PDF 文件

        Args:
            pdf_path: PDF 文件路径
            num_pages: 预估页数（用于计算超时）

        Returns:
            {"markdown": "识别文本", "pages": N, "raw_response": {...}}
        """
        file_b64 = self._encode_file_b64(pdf_path)
        # 根据页数计算超时
        timeout = max(300, (num_pages or 50) * get_settings().ocr_pdf_page_timeout + 60)
        data = await self._call_layout_parsing(file_b64, file_type=0, timeout=timeout)
        return self._parse_response(data)

    def _parse_response(self, data: dict) -> dict:
        """解析 HPS 响应，提取 markdown、结构化 JSON、图片和页数"""
        error_code = data.get("errorCode", -1)
        if error_code != 0:
            raise Exception(f"OCR 处理失败: {data.get('errorMsg', '未知错误')}")

        result = data.get("result", {})
        layout_results = result.get("layoutParsingResults", [])
        data_info = result.get("dataInfo", {})

        # 提取 markdown 文本 + 图片
        markdown_parts = []
        images = {}  # {filename: base64_data}
        for lr in layout_results:
            md = lr.get("markdown", {})
            text = md.get("text", "")
            page_images = md.get("images", {})
            if page_images and isinstance(page_images, dict):
                for img_path, img_b64 in page_images.items():
                    # img_path 形如 "imgs/img_in_header_image_box_xxx.jpg"
                    fname = os.path.basename(img_path)
                    # 避免重名：加页码前缀
                    images[fname] = img_b64
                    # 在 markdown text 中对应的图片 block 位置插入引用
                    img_ref = f"\n\n![{fname}](images/{fname})\n\n"
                    # 如果 text 中有对应位置标记，替换；否则追加到末尾
                    text += img_ref
            if text:
                markdown_parts.append(text)

        markdown_text = "\n\n".join(markdown_parts)
        num_pages = data_info.get("numPages", len(layout_results))

        # 提取结构化内容（按页按块）
        structured_pages = []
        for page_idx, lr in enumerate(layout_results):
            pruned = lr.get("prunedResult", {})
            blocks = pruned.get("parsing_res_list", [])
            page_blocks = []
            for b in blocks:
                page_blocks.append({
                    "id": b.get("block_id"),
                    "global_id": b.get("global_block_id"),
                    "type": b.get("block_label", "text"),
                    "content": b.get("block_content", ""),
                    "bbox": b.get("block_bbox"),
                    "order": b.get("block_order"),
                })
            structured_pages.append({
                "page": page_idx + 1,
                "width": pruned.get("width"),
                "height": pruned.get("height"),
                "blocks": page_blocks,
            })

        return {
            "markdown": markdown_text,
            "pages": num_pages,
            "structured": structured_pages,
            "images": images,
        }

    async def health_check(self) -> bool:
        """检查 OCR 服务健康状态"""
        try:
            async with aiohttp.ClientSession() as client:
                async with client.get(
                    f"{self.base_url}/health",
                    timeout=aiohttp.ClientTimeout(total=get_settings().ocr_health_timeout),
                ) as resp:
                    data = await resp.json()
                    return data.get("errorCode") == 0
        except Exception:
            return False


# 单例
ocr_client = OCRClient()
