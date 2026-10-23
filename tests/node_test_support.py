"""Shared Node executable selection; dependencies are never installed by tests."""
import os
import shutil

NODE = os.environ.get("NODE_BINARY") or shutil.which("node") or "node"
