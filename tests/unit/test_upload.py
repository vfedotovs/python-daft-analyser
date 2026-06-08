"""Unit tests for upload_to_s3.upload_file (no real S3 needed)."""

from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError


class TestUploadFileUnit:
    """Unit tests for the upload_file function (no real S3 needed)."""

    def test_upload_fails_without_s3_bucket(self, monkeypatch):
        """upload_file should return False when S3_BUCKET is not set."""
        monkeypatch.delenv("S3_BUCKET", raising=False)
        from daft_analyser.storage.s3 import upload_file

        assert upload_file("dummy.json", "sale/") is False

    def test_upload_succeeds_with_mocked_s3(self, monkeypatch, tmp_path):
        """upload_file should return True when S3 upload succeeds."""
        monkeypatch.setenv("S3_BUCKET", "test-bucket")

        # Create a temp file to upload
        test_file = tmp_path / "test.json"
        test_file.write_text('[{"address": "test"}]')

        mock_client = MagicMock()
        with patch("daft_analyser.storage.s3.boto3.client", return_value=mock_client):
            from daft_analyser.storage.s3 import upload_file

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

        mock_client = MagicMock()
        mock_client.upload_file.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}},
            "PutObject",
        )
        with patch("daft_analyser.storage.s3.boto3.client", return_value=mock_client):
            from daft_analyser.storage.s3 import upload_file

            result = upload_file(str(test_file), "sale/")

        assert result is False
