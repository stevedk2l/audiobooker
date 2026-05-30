#!/usr/bin/env python3
"""Thin compatibility wrapper – delegates to the audiobooker package.

All logic now lives in audiobooker/.  This file is kept so that
run_audiobook_pipeline.sh and any other callers that invoke
``python3 ebook_audiobook_converter.py`` continue to work.
"""
from __future__ import annotations

import sys

from audiobooker.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
# ---------- end of wrapper ----------

