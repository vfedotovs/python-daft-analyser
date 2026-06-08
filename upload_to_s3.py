#!/usr/bin/env python3
"""Thin entry point — see daft_analyser.storage.s3."""

from daft_analyser.storage.s3 import main, upload_file  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
