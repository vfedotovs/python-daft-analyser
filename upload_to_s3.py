#!/usr/bin/env python3
"""Upload a local file to S3."""

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


if __name__ == "__main__":
    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    if len(sys.argv) != 3:
        logger.error("Usage: %s <local_file> <s3_prefix>", sys.argv[0])
        sys.exit(1)

    local_file = sys.argv[1]
    s3_prefix = sys.argv[2]

    if not os.path.isfile(local_file):
        logger.error("File not found: %s", local_file)
        sys.exit(1)

    success = upload_file(local_file, s3_prefix)
    sys.exit(0 if success else 1)
