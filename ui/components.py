import io
from typing import List, Callable
from nicegui import ui
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PhD_Connect.models.schemas import SupervisorInfo


def create_search_form(on_search: Callable):
    """创建搜索表单，返回查询按钮"""
    with ui.card().style('width: 100%; max-width: 1200px; margin: 20px auto;'):
        ui.label('请填写查询条件，支持任意组合：学校 + 专业、单独专业（多校查询）、导师姓名（精确匹配）').classes('text-subtitle1 text-grey-7')

        ui.separator()

        with ui.row().classes('w-full gap-4 items-end'):
            school_input = ui.input(label='学校', placeholder='请输入学校名称').classes('flex-1')
            major_input = ui.input(label='专业', placeholder='请输入专业名称').classes('flex-1')
            school_level_select = ui.select(
                label='院校层次',
                options=['无', '985', '211', '双非'],
                value='无'
            ).classes('flex-1')
            search_btn = ui.button('查询').props('color=primary')

        # 博导名字：动态输入框列表
        supervisor_inputs = []
        supervisor_container = ui.column().classes('w-full gap-2')

        def add_supervisor_input():
            if len(supervisor_inputs) >= 5:
                ui.notify('最多支持5位导师', type='warning')
                return

            with supervisor_container:
                with ui.row().classes('w-full gap-2 items-center'):
                    inp = ui.input(
                        label=f'博导名字 {len(supervisor_inputs) + 1}',
                        placeholder='请输入导师姓名'
                    ).classes('flex-1')
                    supervisor_inputs.append(inp)

                    # 删除按钮
                    if len(supervisor_inputs) > 1:
                        def make_remove(input_ref, row_ref):
                            def remove():
                                supervisor_inputs.remove(input_ref)
                                row_ref.delete()
                            return remove

                        row_ref = inp.parent_slot.parent
                        ui.button(icon='delete', on_click=make_remove(inp, row_ref)).props('flat color=negative')

        # 初始添加一个输入框
        add_supervisor_input()

        # 添加按钮
        with ui.row().classes('w-full'):
            ui.button('+ 添加导师', on_click=add_supervisor_input).props('flat color=primary')

            async def _on_click():
                # 收集所有非空的导师名字
                names = [inp.value.strip() for inp in supervisor_inputs if inp.value and inp.value.strip()]
                names_str = ','.join(names)
                # 如果选择了"无"，传 None
                level = school_level_select.value if school_level_select.value != '无' else None
                await on_search(
                    search_btn,
                    school_input.value,
                    major_input.value,
                    names_str,
                    level,
                )

            search_btn.on('click', _on_click)

    return search_btn


def _export_pdf(supervisors: List[SupervisorInfo]) -> bytes:
    """将导师列表导出为 PDF 文件，每个导师占一页"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)

    # 注册中文字体（使用系统自带的字体）
    try:
        # Windows 系统字体路径
        pdfmetrics.registerFont(TTFont('SimSun', 'C:/Windows/Fonts/simsun.ttc'))
        pdfmetrics.registerFont(TTFont('SimHei', 'C:/Windows/Fonts/simhei.ttf'))
    except:
        # 如果字体加载失败，使用默认字体（可能无法显示中文）
        pass

    # 定义样式
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontName='SimHei',
        fontSize=18,
        spaceAfter=12,
    )
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontName='SimSun',
        fontSize=12,
        leading=20,
    )

    story = []

    for i, s in enumerate(supervisors):
        # 标题（只显示姓名）
        title = s.name
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 0.5*cm))

        # 详细信息
        info_lines = [
            f"<b>职称：</b>{s.title}",
            f"<b>所属学校：</b>{s.school} ({s.school_level})",
            f"<b>所属院系：</b>{s.college}",
            f"<b>研究方向：</b>{s.research_direction}",
        ]

        if s.phone:
            info_lines.append(f"<b>电话：</b>{s.phone}")
        if s.email:
            info_lines.append(f"<b>邮箱：</b>{s.email}")
        if s.homepage:
            info_lines.append(f"<b>个人主页：</b>{s.homepage}")
        if s.recruitment_info:
            info_lines.append(f"<b>招生信息：</b>{s.recruitment_info}")

        for line in info_lines:
            story.append(Paragraph(line, normal_style))
            story.append(Spacer(1, 0.3*cm))

        # 如果不是最后一个导师，添加分页符
        if i < len(supervisors) - 1:
            story.append(PageBreak())

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def create_supervisor_card(supervisor: SupervisorInfo):
    """创建导师详情卡片"""
    with ui.card().classes('w-full'):
        ui.label(f'{supervisor.name}').classes('text-h5')
        ui.separator()

        with ui.column().classes('gap-2'):
            ui.label(f'职称：{supervisor.title}')
            ui.label(f'所属学校：{supervisor.school} ({supervisor.school_level})')
            ui.label(f'所属院系：{supervisor.college}')
            ui.label(f'研究方向：{supervisor.research_direction}')
            if supervisor.phone:
                ui.label(f'电话：{supervisor.phone}')
            if supervisor.email:
                ui.label(f'邮箱：{supervisor.email}')
            if supervisor.homepage:
                with ui.row().classes('gap-1 items-center'):
                    ui.label('个人主页：')
                    ui.link(supervisor.homepage, supervisor.homepage, new_tab=True)
            ui.label(f'招生信息：{supervisor.recruitment_info if supervisor.recruitment_info else "暂无"}')


def create_supervisor_cards_with_export(supervisors: List[SupervisorInfo], school: str = None, major: str = None, names: list = None):
    """创建导师详情卡片列表，含导出 PDF 按钮"""
    # 生成文件名
    filename_parts = []
    if school:
        filename_parts.append(school)
    if major:
        filename_parts.append(major)
    if names:
        filename_parts.extend(names)
    filename = '_'.join(filename_parts) if filename_parts else '博导详情'
    filename = filename + '.pdf'

    # Export button
    with ui.row().classes('w-full justify-end q-mb-sm'):
        def do_export_pdf():
            data = _export_pdf(supervisors)
            ui.download(data, filename=filename)

        ui.button('导出 PDF', on_click=do_export_pdf, icon='picture_as_pdf').props('color=secondary outline')

    # 显示所有导师卡片
    for supervisor in supervisors:
        create_supervisor_card(supervisor)


def _export_excel(supervisors: List[SupervisorInfo]) -> bytes:
    """将导师列表导出为 Excel 文件"""
    wb = Workbook()
    ws = wb.active
    ws.title = "博导信息"

    headers = ["学校层次", "学校", "相关学院", "招生专业", "导师", "电话", "邮箱", "个人主页"]
    ws.append(headers)

    for idx, s in enumerate(supervisors, start=2):  # 从第2行开始（第1行是表头）
        ws.append([
            s.school_level,
            s.school,
            s.college,
            s.major,
            s.name,
            s.phone,
            s.email,
            s.homepage,
        ])
        # 如果有个人主页，设置为超链接
        if s.homepage:
            cell = ws.cell(row=idx, column=8)  # 第8列是个人主页
            cell.hyperlink = s.homepage
            cell.style = "Hyperlink"

    # Auto-width
    for col in ws.columns:
        max_len = 0
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.read()


def create_supervisor_table(supervisors: List[SupervisorInfo], school: str = None, major: str = None, names: list = None):
    """创建导师列表表格，含导出按钮"""
    # 生成文件名
    filename_parts = []
    if school:
        filename_parts.append(school)
    if major:
        filename_parts.append(major)
    if names:
        filename_parts.extend(names)
    filename = '_'.join(filename_parts) if filename_parts else '博导信息'
    filename = filename + '.xlsx'

    # Export button
    with ui.row().classes('w-full justify-end q-mb-sm'):
        def do_export():
            data = _export_excel(supervisors)
            ui.download(data, filename=filename)

        ui.button('导出 Excel', on_click=do_export, icon='download').props('color=secondary outline')

    columns = [
        {'name': 'school_level', 'label': '学校层次', 'field': 'school_level', 'align': 'left', 'sortable': True},
        {'name': 'school', 'label': '学校', 'field': 'school', 'align': 'left'},
        {'name': 'college', 'label': '相关学院', 'field': 'college', 'align': 'left'},
        {'name': 'major', 'label': '招生专业', 'field': 'major', 'align': 'left'},
        {'name': 'name', 'label': '导师', 'field': 'name', 'align': 'left'},
        {'name': 'phone', 'label': '电话', 'field': 'phone', 'align': 'left'},
        {'name': 'email', 'label': '邮箱', 'field': 'email', 'align': 'left'},
        {'name': 'homepage', 'label': '个人主页', 'field': 'homepage', 'align': 'left'},
    ]

    rows = [
        {
            'school_level': s.school_level or '双非',
            'school': s.school or '-',
            'college': s.college or '-',
            'major': s.major or '-',
            'name': s.name or '-',
            'phone': s.phone or '-',
            'email': s.email or '-',
            'homepage': s.homepage or '-',
        }
        for s in supervisors
    ]

    table = ui.table(columns=columns, rows=rows, row_key='name').classes('w-full').props('flat bordered')

    # 自定义个人主页列为超链接
    table.add_slot('body-cell-homepage', '''
        <q-td :props="props">
            <a v-if="props.value && props.value !== '-'" :href="props.value" target="_blank" style="color: #1976d2; text-decoration: underline;">
                {{ props.value }}
            </a>
            <span v-else>-</span>
        </q-td>
    ''')
