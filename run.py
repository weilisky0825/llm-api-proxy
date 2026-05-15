#!/usr/bin/env python3
"""Standalone entry point for PyInstaller packaging."""
import sys
import os

if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)

import uvicorn
from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
