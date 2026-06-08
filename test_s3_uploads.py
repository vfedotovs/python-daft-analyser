#!/usr/bin/env python3
"""Tests to verify scraper JSON files were uploaded to S3 and are not empty.

Integration tests connect to the real S3 bucket using credentials from
environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET).

Usage:
    # Run all tests
    pytest test_s3_uploads.py -v

    # Run only today's upload verification
    pytest test_s3_uploads.py -v -k "today"

    # Run with a specific date (YYYYMMDD)
    S3_CHECK_DATE=20260302 pytest test_s3_uploads.py -v
"""

import os
from datetime import datetime, timezone

import boto3
import pytest

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
        import json

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
        import json

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


# ── Unit tests for upload_file() ───────────────────────────────────


class TestUploadFileUnit:
    """Unit tests for the upload_file function (no real S3 needed)."""

    def test_upload_fails_without_s3_bucket(self, monkeypatch):
        """upload_file should return False when S3_BUCKET is not set."""
        monkeypatch.delenv("S3_BUCKET", raising=False)
        from upload_to_s3 import upload_file

        assert upload_file("dummy.json", "sale/") is False

    def test_upload_succeeds_with_mocked_s3(self, monkeypatch, tmp_path):
        """upload_file should return True when S3 upload succeeds."""
        monkeypatch.setenv("S3_BUCKET", "test-bucket")

        # Create a temp file to upload
        test_file = tmp_path / "test.json"
        test_file.write_text('[{"address": "test"}]')

        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        with patch("upload_to_s3.boto3.client", return_value=mock_client):
            from upload_to_s3 import upload_file

            result = upload_file(str(test_file), "sale/")

        assert result is True
        mock_client.upload_file.assert_called_once_with(
            str(test_file), "test-bucket", "sale/test.json"
        )

    def test_upload_returns_false_on_client_error(self, monkeypatch, tmp_path):
        """upload_file should return False when S3 raises a ClientError."""
        monkeypatch.setenv("S3_BUCKET", "test-bucket")

        test_file = tmp_path / "test.json"
        test_file.write_text('[{"address": "test"}]')

        from unittest.mock import MagicMock, patch

        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.upload_file.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}},
            "PutObject",
        )
        with patch("upload_to_s3.boto3.client", return_value=mock_client):
            from upload_to_s3 import upload_file

            result = upload_file(str(test_file), "sale/")

        assert result is False
