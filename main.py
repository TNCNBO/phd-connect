import sys
import os

# 让 PhD_Connect 作为包可被导入（需要父目录在 sys.path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import PhD_Connect.app  # 注册 @ui.page 路由
from nicegui import ui

if __name__ == "__main__":
    ui.run(host='0.0.0.0', port=8080, title='博导建联', reload=False, storage_secret='phd-connect-secret')
