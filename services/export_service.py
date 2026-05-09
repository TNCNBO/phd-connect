from typing import List
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PhD_Connect.models.schemas import SupervisorInfo
import os


class ExportService:
    """导出服务"""

    def __init__(self):
        # 注册中文字体（如果有的话）
        # pdfmetrics.registerFont(TTFont('SimSun', 'simsun.ttc'))
        pass

    def export_to_pdf(self, supervisors: List[SupervisorInfo], output_path: str) -> str:
        """
        导出导师信息为 PDF

        Args:
            supervisors: 导师信息列表
            output_path: 输出文件路径

        Returns:
            生成的 PDF 文件路径
        """
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        story = []
        styles = getSampleStyleSheet()

        # 标题样式
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=12,
        )

        # 内容样式
        content_style = ParagraphStyle(
            'CustomContent',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=6,
        )

        # 添加每个导师的信息
        for i, supervisor in enumerate(supervisors, 1):
            # 导师姓名作为标题
            story.append(Paragraph(f"{i}. {supervisor.name} - {supervisor.title}", title_style))
            story.append(Spacer(1, 0.2*cm))

            # 详细信息
            info_lines = [
                f"<b>学校：</b>{supervisor.school}",
                f"<b>学院：</b>{supervisor.college}",
                f"<b>专业：</b>{supervisor.major}",
                f"<b>导师类型：</b>{supervisor.supervisor_type}",
                f"<b>研究方向：</b>{supervisor.research_direction}",
                f"<b>联系方式：</b>{supervisor.contact}",
                f"<b>个人主页：</b>{supervisor.homepage}",
                f"<b>招生信息：</b>{supervisor.recruitment_info}",
            ]

            for line in info_lines:
                story.append(Paragraph(line, content_style))

            story.append(Spacer(1, 0.5*cm))

        # 生成 PDF
        doc.build(story)
        return output_path

    def export_to_excel(self, supervisors: List[SupervisorInfo], output_path: str) -> str:
        """
        导出导师信息为 Excel

        Args:
            supervisors: 导师信息列表
            output_path: 输出文件路径

        Returns:
            生成的 Excel 文件路径
        """
        # 这里简化处理，实际应该使用 openpyxl 或调用 spreadsheets 技能
        # 暂时返回路径
        return output_path
