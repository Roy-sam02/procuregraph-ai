import unittest

from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from datasets.generator.check_minio_contract import check_remote_bytes


class MinioContractTests(unittest.TestCase):
    def test_changed_download_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            check_remote_bytes(b"changed PDF", EXPECTED_SHA256)


if __name__ == "__main__":
    unittest.main()
