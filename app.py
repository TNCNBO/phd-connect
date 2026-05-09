import asyncio
import logging
import os
import structlog
from dotenv import load_dotenv
from nicegui import ui, app

from PhD_Connect.services.search_service import SupervisorSearchService
from PhD_Connect.models.schemas import SearchRequest
from PhD_Connect.ui.components import create_search_form, create_supervisor_cards_with_export, create_supervisor_table

# structlog setup (matches src/config/logging_config.py pattern)
logging.basicConfig(format="%(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.WARNING)
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger("phd_connect")

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
PHD_LOGIN_PASSWORD = os.getenv("PHD_LOGIN_PASSWORD", "phd2026")
search_service = SupervisorSearchService()


def _client_alive() -> bool:
    """Check whether the current NiceGUI client is still connected."""
    try:
        from nicegui import context
        client = context.client
        if client is None:
            return False
        # Check both socket connection and client state
        return hasattr(client, 'has_socket_connection') and client.has_socket_connection
    except (RuntimeError, AttributeError, Exception) as e:
        logger.debug("client_check_failed", error=str(e))
        return False


def _validate_input(school: str, major: str, supervisor_names_str: str, school_level: str) -> str | None:
    """前置输入校验，返回错误信息或 None"""
    if not school and not major and not supervisor_names_str and not school_level:
        return "请输入查询条件"
    if school and not major and not supervisor_names_str:
        return "请输入专业信息"
    if not school and not major and not supervisor_names_str and school_level:
        return "请输入专业信息"
    return None


async def on_search_click(btn, school: str, major: str, supervisor_names_str: str, school_level: str,
                          result_container, loading_spinner, thinking_label, status_label):
    """按钮点击回调 — 校验通过后直接执行搜索（async，保留 UI 上下文）"""
    logger.info("search_click", school=school, major=major, names=supervisor_names_str, level=school_level)

    if not _client_alive():
        logger.warning("search_click_client_dead")
        return

    error = _validate_input(school, major, supervisor_names_str, school_level)
    if error:
        try:
            ui.notify(error, type='warning')
        except RuntimeError:
            logger.warning("notify_failed_client_dead")
        return

    try:
        btn.props('disable')
        await asyncio.sleep(0)  # flush disable message to client
    except RuntimeError:
        logger.warning("button_disable_failed_client_dead")
        return

    await handle_search(btn, school, major, supervisor_names_str, school_level,
                       result_container, loading_spinner, thinking_label, status_label)


async def handle_search(btn, school: str, major: str, supervisor_names_str: str, school_level: str,
                       result_container, loading_spinner, thinking_label, status_label):
    if not _client_alive():
        logger.info("handle_search_client_check_failed")
        return

    logger.info("handle_search_start", client_alive=_client_alive())

    try:
        result_container.clear()
        loading_spinner.set_visibility(True)
        status_label.set_visibility(True)
        logger.info("ui_elements_initialized", spinner_visible=True, label_visible=True)
    except RuntimeError as e:
        logger.warning("ui_init_failed", error=str(e))
        return

    supervisor_names = []
    if supervisor_names_str:
        supervisor_names = [name.strip() for name in supervisor_names_str.split(',') if name.strip()]

    try:
        request = SearchRequest(
            school=school if school else None,
            major=major if major else None,
            supervisor_names=supervisor_names,
            school_level=school_level if school_level else None
        )

        logger.info("search_start", school=school, major=major, names=supervisor_names)

        # 心跳：流事件间隙保持 WebSocket 活跃
        last_status = ""
        dots = 0
        heartbeat_active = True

        async def heartbeat():
            nonlocal dots
            while heartbeat_active:
                if last_status:
                    status_label.set_text(last_status + "." * (dots % 4))
                dots += 1
                await asyncio.sleep(1.5)

        heartbeat_task = asyncio.create_task(heartbeat())

        async for event in search_service.search_stream(request):
            logger.info("event_received", event_type=event["type"])
            if event["type"] == "status":
                last_status = event["text"]
                dots = 0
                logger.info("status_update", text=last_status, client_alive=_client_alive())
                if _client_alive():
                    try:
                        status_label.set_text(last_status)
                        await asyncio.sleep(0)
                    except RuntimeError:
                        logger.warning("status_update_failed_client_gone")
                        return
            elif event["type"] == "thinking":
                logger.info("thinking_update", text=event["text"], client_alive=_client_alive())
                if _client_alive():
                    try:
                        thinking_label.set_visibility(True)
                        thinking_label.set_text(event["text"])
                        await asyncio.sleep(0)
                    except RuntimeError:
                        logger.warning("thinking_update_failed_client_gone")
                        return
            elif event["type"] == "result":
                heartbeat_active = False
                heartbeat_task.cancel()
                logger.info("search_done", mode=event["mode"], count=len(event["supervisors"]))
                if not _client_alive():
                    logger.info("client_gone_during_search")
                    return
                try:
                    with result_container:
                        ui.label('查询结果如下：').classes('text-h5 q-mb-md')

                        if event["mode"] == "detail":
                            create_supervisor_cards_with_export(
                                event["supervisors"],
                                school=school,
                                major=major,
                                names=supervisor_names
                            )
                            if not event["supervisors"]:
                                ui.label('未找到匹配的导师信息').classes('text-grey-7')
                        else:
                            if event["supervisors"]:
                                ui.label(f'共找到 {len(event["supervisors"])} 位导师').classes('text-subtitle1 q-mb-sm')
                                create_supervisor_table(
                                    event["supervisors"],
                                    school=school,
                                    major=major,
                                    names=supervisor_names
                                )
                            else:
                                ui.label('未找到导师列表').classes('text-grey-7')
                except RuntimeError as e:
                    logger.warning("result_render_failed", error=str(e))
                    return
            elif event["type"] == "error":
                logger.error("search_error", error=event["text"])
                if _client_alive():
                    try:
                        ui.notify(event["text"], type="negative")
                    except RuntimeError:
                        logger.warning("error_notify_failed_client_dead")

    except Exception as e:
        logger.error("search_error", exc_info=True)
        if _client_alive():
            try:
                ui.notify(f"查询失败: {e}", type="negative")
            except RuntimeError:
                logger.warning("exception_notify_failed_client_dead")
    finally:
        heartbeat_active = False
        try:
            heartbeat_task.cancel()
        except NameError:
            pass
        if _client_alive():
            try:
                loading_spinner.set_visibility(False)
                thinking_label.set_visibility(False)
                status_label.set_visibility(False)
                btn.props(remove='disable')
            except RuntimeError:
                logger.warning("cleanup_failed_client_dead")


@ui.page('/')
def index():
    ui.colors(primary='#1976D2')

    if not app.storage.user.get('authenticated'):
        with ui.column().classes('w-full items-center'):
            ui.label('博导建联').classes('text-h3 q-mt-xl')
            ui.label('请输入用户名和密码登录').classes('text-body1 text-grey-7 q-mt-sm q-mb-md')

            username_input = ui.input('用户名').classes('q-mb-sm').props('outlined')
            password_input = ui.input('密码').props('type=password outlined')
            error_label = ui.label('').classes('text-red-5 text-body2 q-mt-sm')

            async def do_login():
                if username_input.value == 'admin' and password_input.value == PHD_LOGIN_PASSWORD:
                    app.storage.user['authenticated'] = True
                    ui.navigate.reload()
                else:
                    error_label.set_text('用户名或密码错误')

            ui.button('登录', on_click=do_login).props('color=primary').classes('q-mt-md')
        return

    def do_logout():
        app.storage.user.clear()
        ui.navigate.reload()

    with ui.column().classes('w-full items-center'):
        with ui.row().classes('w-full justify-between items-center'):
            ui.label('博导建联').classes('text-h3 q-mt-lg')
            ui.button('退出登录', on_click=do_logout).props('flat color=grey')

        # Create search form first
        # We'll pass the callback after creating UI elements
        search_form_container = ui.column().classes('w-full')

        with ui.column().classes('items-center q-mt-md'):
            loading_spinner = ui.spinner(size='lg').props('color=primary')
            loading_spinner.set_visibility(False)
            thinking_label = ui.label('').classes('text-grey-5 text-body2 q-mt-sm italic')
            thinking_label.set_visibility(False)
            status_label = ui.label('').classes('text-grey-6 text-body2 q-mt-sm')
            status_label.set_visibility(False)

        result_container = ui.column().classes('w-full q-mt-md q-px-md')

        # Now create the search form with callback
        with search_form_container:
            def make_search_callback():
                async def callback(btn, school, major, names_str, level):
                    await on_search_click(btn, school, major, names_str, level,
                                        result_container, loading_spinner, thinking_label, status_label)
                return callback

            create_search_form(make_search_callback())


