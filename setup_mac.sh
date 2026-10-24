#!/bin/bash
# 在 macOS 自带 Python 3.9 上安装（无需 brew）
set -e
cd "$(dirname "$0")"
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt
venv/bin/python -m starmoe_ios --help >/dev/null && echo "安装完成"
