#!/usr/bin/env python
"""Simple test runner."""
import sys
import importlib
mod = importlib.import_module("_pytest")
mod.main(sys.argv[1:] or ["tests/", "-q", "--tb=short"])
