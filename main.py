import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import app  # 注册 @ui.page 路由  # noqa: E402
from nicegui import ui

if __name__ == "__main__":
    ui.run(host='0.0.0.0', port=8080, title='博导建联', reload=False, storage_secret='phd-connect-secret')
