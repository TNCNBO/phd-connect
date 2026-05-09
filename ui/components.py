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
from models.schemas import SupervisorInfo


def create_search_form(on_search: Callable):
    """创建搜索表单，返回查询按钮"""
    with ui.card().classes('q-pa-lg').style('width: 100%; max-width: 900px; margin: 24px auto; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.08);'):
        with ui.row().classes('items-center gap-2 q-mb-md'):
            ui.icon('search').props('color=primary size=sm')
            ui.label('查询条件').classes('text-subtitle1 text-weight-medium')
        ui.label('支持学校+专业组合查询、多校查询或导师姓名精确匹配').classes('text-body2 text-grey-6 q-mb-sm')

        with ui.row().classes('w-full gap-4 items-end q-mb-md'):
            school_input = ui.input(label='学校', placeholder='如：清华大学').props('outlined dense').classes('flex-1')
            major_input = ui.input(label='专业', placeholder='如：计算机科学与技术').props('outlined dense').classes('flex-1')
            school_level_select = ui.select(
                label='院校层次',
                options=['无', '985', '211', '双非'],
                value='无'
            ).props('outlined dense').classes('flex-1')
            search_btn = ui.button('查询', icon='search').props('color=primary unelevated').style('height: 40px;')

        # 博导名字区域
        ui.separator().classes('q-mb-sm')
        supervisor_inputs = []
        supervisor_container = ui.column().classes('w-full gap-2')

        def add_supervisor_input():
            if len(supervisor_inputs) >= 5:
                ui.notify('最多支持5位导师', type='warning')
                return
            with supervisor_container:
                with ui.row().classes('w-full gap-2 items-center'):
                    inp = ui.input(
                        label=f'导师姓名 {len(supervisor_inputs) + 1}',
                        placeholder='输入导师姓名可按姓名精确查找'
                    ).props('outlined dense').classes('flex-1')
                    supervisor_inputs.append(inp)
                    if len(supervisor_inputs) > 1:
                        def make_remove(input_ref, row_ref):
                            def remove():
                                supervisor_inputs.remove(input_ref)
                                row_ref.delete()
                            return remove
                        row_ref = inp.parent_slot.parent
                        ui.button(icon='close', on_click=make_remove(inp, row_ref)).props('flat round dense color=negative')

        add_supervisor_input()

        with ui.row().classes('w-full q-mt-sm'):
            ui.button('+ 添加导师', on_click=add_supervisor_input, icon='person_add').props('flat dense color=primary')

            async def _on_click():
                names = [inp.value.strip() for inp in supervisor_inputs if inp.value and inp.value.strip()]
                names_str = ','.join(names)
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
    with ui.card().classes('q-pa-lg').style('width: 100%; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,0.06);'):
        with ui.row().classes('items-center gap-3 q-mb-md'):
            ui.icon('person').props('color=primary size=md')
            with ui.column().classes('gap-0'):
                ui.label(supervisor.name).classes('text-h6 text-weight-medium')
                ui.label(f'{supervisor.title}  |  {supervisor.college}').classes('text-body2 text-grey-7')

        ui.separator().classes('q-mb-md')

        fields = [
            ('business', '所属学校', f'{supervisor.school} ({supervisor.school_level})'),
            ('science', '研究方向', supervisor.research_direction),
            ('info', '招生信息', supervisor.recruitment_info or '暂无'),
        ]
        for icon_name, label, value in fields:
            with ui.row().classes('items-center gap-3 q-mb-sm'):
                ui.icon(icon_name).props('color=grey-6 size=sm')
                ui.label(label).classes('text-caption text-grey-6')
                ui.label(value).classes('text-body2 text-weight-medium')

        # 联系方式
        has_contact = supervisor.phone or supervisor.email or supervisor.homepage
        if has_contact:
            ui.separator().classes('q-mb-sm')
            with ui.row().classes('gap-4'):
                if supervisor.phone:
                    with ui.row().classes('items-center gap-1'):
                        ui.icon('call').props('color=green size=xs')
                        ui.label(supervisor.phone).classes('text-body2')
                if supervisor.email:
                    with ui.row().classes('items-center gap-1'):
                        ui.icon('email').props('color=blue size=xs')
                        ui.label(supervisor.email).classes('text-body2')
                if supervisor.homepage:
                    with ui.row().classes('items-center gap-1'):
                        ui.icon('link').props('color=purple size=xs')
                        ui.link(supervisor.homepage, supervisor.homepage, new_tab=True).classes('text-body2')


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
    with ui.row().classes('w-full justify-end q-mb-md'):
        def do_export_pdf():
            data = _export_pdf(supervisors)
            ui.download(data, filename=filename)
        ui.button('导出 PDF', on_click=do_export_pdf, icon='picture_as_pdf').props('color=primary outline').style('border-radius: 8px;')

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
    with ui.row().classes('w-full justify-end q-mb-md'):
        def do_export():
            data = _export_excel(supervisors)
            ui.download(data, filename=filename)
        ui.button('导出 Excel', on_click=do_export, icon='download').props('color=primary outline').style('border-radius: 8px;')

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

    table = ui.table(columns=columns, rows=rows, row_key='name').classes('w-full').props('flat bordered separator=horizontal').style('border-radius: 8px; overflow: hidden;')

    # 自定义个人主页列为超链接
    table.add_slot('body-cell-homepage', '''
        <q-td :props="props">
            <a v-if="props.value && props.value !== '-'" :href="props.value" target="_blank" style="color: #1976d2; text-decoration: underline;">
                {{ props.value }}
            </a>
            <span v-else>-</span>
        </q-td>
    ''')
