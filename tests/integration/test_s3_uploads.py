"""Integration tests verifying scraper JSON files were uploaded to S3.

These connect to the real S3 bucket using credentials from environment
variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET). They are
marked ``integration`` so they can be deselected in CI:

Usage:
    # Run only unit tests (skip these)
    pytest -m "not integration"

    # Run integration tests
    pytest -m integration -v

    # Run with a specific date (YYYYMMDD)
    S3_CHECK_DATE=20260302 pytest -m integration -v
"""

import json
import os
from datetime import datetime, timezone

import boto3
import pytest

# Every test in this module hits real AWS S3.
pytestmark = pytest.mark.integration

S3_BUCKET = os.environ.get("S3_BUCKET")
S3_CHECK_DATE = os.environ.get("S3_CHECK_DATE", datetime.now(timezone.utc).strftime("%Y%m%d"))


@pytest.fixture(scope="module")
def s3_client():
    """Create a boto3 S3 client."""
    return boto3.client("s3")


@pytest.fixture(scope="module")
def sale_json_objects(s3_client):
    """List all sale JSON objects matching today's date pattern."""
    prefix = f"sale/daft_listings_{S3_CHECK_DATE}"
    response = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
    objects = response.get("Contents", [])
    return [obj for obj in objects if obj["Key"].endswith(".json")]


@pytest.fixture(scope="module")
def rent_json_objects(s3_client):
    """List all rent JSON objects matching today's date pattern."""
    prefix = f"rent/rent_cork_city_{S3_CHECK_DATE}"
    response = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
    objects = response.get("Contents", [])
    return [obj for obj in objects if obj["Key"].endswith(".json")]


def requires_s3():
    """Skip test if S3 credentials or bucket are not configured."""
    return pytest.mark.skipif(
        not S3_BUCKET
        or not os.environ.get("AWS_ACCESS_KEY_ID")
        or not os.environ.get("AWS_SECRET_ACCESS_KEY"),
        reason="S3 credentials or S3_BUCKET not set",
    )


# ── Sale upload tests ──────────────────────────────────────────────


@requires_s3()
class TestSaleUploads:
    """Verify sale JSON files were uploaded to S3."""

    def test_sale_json_files_exist(self, sale_json_objects):
        """At least one sale JSON file should exist for the check date."""
        assert len(sale_json_objects) > 0, (
            f"No sale JSON files found in s3://{S3_BUCKET}/sale/ "
            f"for date {S3_CHECK_DATE}"
        )

    def test_sale_json_files_not_empty(self, sale_json_objects):
        """All sale JSON files should have a size greater than 0 bytes."""
        for obj in sale_json_objects:
            assert obj["Size"] > 0, (
                f"Sale file {obj['Key']} is 0 bytes"
            )

    def test_sale_json_content_is_valid(self, s3_client, sale_json_objects):
        """Sale JSON files should contain valid JSON with listing data."""
        for obj in sale_json_objects:
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=obj["Key"])
            body = response["Body"].read().decode("utf-8")
            data = json.loads(body)
            assert isinstance(data, list), (
                f"Sale file {obj['Key']} is not a JSON array"
            )
            assert len(data) > 0, (
                f"Sale file {obj['Key']} has an empty listings array"
            )


# ── Rent upload tests ──────────────────────────────────────────────


@requires_s3()
class TestRentUploads:
    """Verify rent JSON files were uploaded to S3."""

    def test_rent_json_files_exist(self, rent_json_objects):
        """At least one rent JSON file should exist for the check date."""
        assert len(rent_json_objects) > 0, (
            f"No rent JSON files found in s3://{S3_BUCKET}/rent/ "
            f"for date {S3_CHECK_DATE}"
        )

    def test_rent_json_files_not_empty(self, rent_json_objects):
        """All rent JSON files should have a size greater than 0 bytes."""
        for obj in rent_json_objects:
            assert obj["Size"] > 0, (
                f"Rent file {obj['Key']} is 0 bytes"
            )

    def test_rent_json_content_is_valid(self, s3_client, rent_json_objects):
        """Rent JSON files should contain valid JSON with listing data."""
        for obj in rent_json_objects:
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=obj["Key"])
            body = response["Body"].read().decode("utf-8")
            data = json.loads(body)
            assert isinstance(data, list), (
                f"Rent file {obj['Key']} is not a JSON array"
            )
            assert len(data) > 0, (
                f"Rent file {obj['Key']} has an empty listings array"
            )
