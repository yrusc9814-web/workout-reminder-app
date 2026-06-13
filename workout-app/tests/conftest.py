import os
import pathlib


_ORIG_IS_FILE = pathlib.Path.is_file


def _safe_is_file(self):
    try:
        return _ORIG_IS_FILE(self)
    except OSError as exc:
        if getattr(exc, 'winerror', 0) == 1337:
            return False
        raise


pathlib.Path.is_file = _safe_is_file