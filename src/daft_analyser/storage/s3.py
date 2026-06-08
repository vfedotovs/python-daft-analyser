#!/usr/bin/env python3
"""Upload a local file to S3."""

from __future__ import annotations

import logging
import os
import sys

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("upload_to_s3")


def upload_file(local_path: str, prefix: str) -> bool:
    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        logger.error("S3_BUCKET environment variable not set")
        return False

    filename = os.path.basename(local_path)
    s3_key = f"{prefix}{filename}"

    try:
        s3 = boto3.client("s3")
        s3.upload_file(local_path, bucket, s3_key)
        logger.info("Uploaded %s -> s3://%s/%s", local_path, bucket, s3_key)
        return True
    except ClientError as e:
        logger.error("Failed to upload %s to s3://%s/%s: %s", local_path, bucket, s3_key, e)
        return False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    args = sys.argv if argv is None else [sys.argv[0], *argv]
    if len(args) != 3:
        logger.error("Usage: %s <local_file> <s3_prefix>", args[0])
        return 1

    local_file = args[1]
    s3_prefix = args[2]

    if not os.path.isfile(local_file):
        logger.error("File not found: %s", local_file)
        return 1

    return 0 if upload_file(local_file, s3_prefix) else 1


if __name__ == "__main__":
    raise SystemExit(main())
