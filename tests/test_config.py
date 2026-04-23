from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from image_retrieval.config import load_dotenv


class ConfigTests(unittest.TestCase):
    def test_load_dotenv_reads_values_without_overriding_existing_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv_path = Path(temp_dir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "REDIS_URL='rediss://default:secret@example.redis-cloud.com:12345'",
                        'REDIS_NAMESPACE="from-file"',
                        "EXISTING_VALUE=from-file",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"EXISTING_VALUE": "from-env"}, clear=True):
                load_dotenv(dotenv_path)

                self.assertEqual(
                    os.environ["REDIS_URL"],
                    "rediss://default:secret@example.redis-cloud.com:12345",
                )
                self.assertEqual(os.environ["REDIS_NAMESPACE"], "from-file")
                self.assertEqual(os.environ["EXISTING_VALUE"], "from-env")


if __name__ == "__main__":
    unittest.main()
