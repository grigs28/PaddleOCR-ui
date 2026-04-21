import re
from docx import Document
from docx.shared import Pt


class ExportService:
    @staticmethod
    def md_to_txt(md_text: str) -> str:
        """Markdown 转纯文本：去除 #、**、[]() 等标记"""
        text = md_text
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)  # 去图片
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # 链接保留文字
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)  # 去标题标记
        text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)  # 去粗体斜体
        text = re.sub(r'`([^`]+)`', r'\1', text)  # 去行内代码
        return text.strip()

    @staticmethod
    def md_to_docx(md_text: str) -> bytes:
        """Markdown 转 DOCX"""
        import io
        doc = Document()
        for line in md_text.split('\n'):
            if line.startswith('# '):
                doc.add_heading(line[2:], level=1)
            elif line.startswith('## '):
                doc.add_heading(line[3:], level=2)
            elif line.startswith('### '):
                doc.add_heading(line[4:], level=3)
            elif line.strip():
                doc.add_paragraph(line)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
