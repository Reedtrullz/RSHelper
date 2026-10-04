"""Authorization policy tests for the dashboard boundary."""
import sys
import unittest

sys.path.insert(0, "src")

from rshelper.dashboard.access import authorize


class TestAuthorizePolicy(unittest.TestCase):
    def test_public_demo_allows_only_market_static_and_sanitized_metadata(self):
        for resource in ("public-market", "static", "sanitized-health", "capabilities"):
            with self.subTest(resource=resource):
                self.assertTrue(authorize("public-demo", None, None, resource, False))

        for resource in ("private-state", "daemon-control"):
            with self.subTest(resource=resource):
                self.assertFalse(authorize("public-demo", None, None, resource, False))

    def test_public_demo_never_allows_mutations(self):
        self.assertFalse(authorize("public-demo", None, None, "public-market", True))
        self.assertFalse(authorize("public-demo", None, None, "private-state", True))

    def test_owner_requires_constant_time_bearer_match(self):
        self.assertTrue(authorize("owner", "Bearer synthetic-secret", "synthetic-secret",
                                  "private-state", False))
        for header in (None, "", "synthetic-secret", "Basic synthetic-secret",
                       "Bearer wrong", "Bearer synthetic-secret extra",
                       "Bearer secrét"):
            with self.subTest(header=header):
                self.assertFalse(authorize("owner", header, "synthetic-secret",
                                           "private-state", False))

    def test_owner_fails_closed_when_token_is_missing(self):
        self.assertFalse(authorize("owner", "Bearer synthetic-secret", None,
                                   "public-market", False))

    def test_unknown_mode_and_resource_fail_closed(self):
        self.assertFalse(authorize("unknown", "Bearer synthetic-secret", "synthetic-secret",
                                   "private-state", False))
        self.assertFalse(authorize("owner", "Bearer synthetic-secret", "synthetic-secret",
                                   "unknown", False))


if __name__ == "__main__":
    unittest.main()
