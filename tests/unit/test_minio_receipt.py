import unittest

from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from datasets.generator.check_minio_contract import BUCKET, object_key
from datasets.generator.register_minio_location import validate_receipt


class MinioReceiptTests(unittest.TestCase):
    def setUp(self):
        self.receipt = {
            "bucket": BUCKET,
            "object_key": object_key(EXPECTED_SHA256),
            "object_version_id": "ebe48aff-094e-497e-b03c-035b79be6742",
            "sha256": EXPECTED_SHA256,
            "document_version": 1,
        }

    def test_valid_readback_receipt(self):
        self.assertEqual(validate_receipt(self.receipt)[2], self.receipt["object_version_id"])

    def test_wrong_object_version_or_hash_is_rejected(self):
        self.receipt["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "disagrees"):
            validate_receipt(self.receipt)
        self.receipt["sha256"] = EXPECTED_SHA256
        self.receipt["object_version_id"] = "null"
        with self.assertRaisesRegex(ValueError, "valid MinIO version"):
            validate_receipt(self.receipt)


if __name__ == "__main__":
    unittest.main()
