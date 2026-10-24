"""PyInstaller / URL Scheme 入口：python packaging/entry.py [moe.starmoe.box://...]"""
import os, sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starmoe_ios.gui.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
