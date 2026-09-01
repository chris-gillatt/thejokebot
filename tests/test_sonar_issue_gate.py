import io
import json
import os
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from scripts import check_sonar_issues


class SonarIssueGateTests(unittest.TestCase):
    def _response(self, total):
        return io.BytesIO(json.dumps({"total": total}).encode())

    def test_passes_when_branch_has_no_unresolved_issues(self):
        with mock.patch.dict(os.environ, {"SONAR_TOKEN": "secret"}, clear=True):
            with mock.patch.object(
                check_sonar_issues.urllib.request,
                "urlopen",
                return_value=self._response(0),
            ) as urlopen:
                result = check_sonar_issues.main(["--branch", "main"])

        self.assertEqual(result, 0)
        request = urlopen.call_args.args[0]
        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(query["branch"], ["main"])
        self.assertNotIn("secret", request.full_url)
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))

    def test_scopes_pull_request_query(self):
        with mock.patch.dict(os.environ, {"SONAR_TOKEN": "secret"}, clear=True):
            with mock.patch.object(
                check_sonar_issues.urllib.request,
                "urlopen",
                return_value=self._response(0),
            ) as urlopen:
                result = check_sonar_issues.main(["--pull-request", "42"])

        self.assertEqual(result, 0)
        query = parse_qs(urlparse(urlopen.call_args.args[0].full_url).query)
        self.assertEqual(query["pullRequest"], ["42"])
        self.assertNotIn("branch", query)

    def test_fails_when_unresolved_issues_remain(self):
        with mock.patch.dict(os.environ, {"SONAR_TOKEN": "secret"}, clear=True):
            with mock.patch.object(
                check_sonar_issues.urllib.request,
                "urlopen",
                return_value=self._response(3),
            ):
                result = check_sonar_issues.main([])

        self.assertEqual(result, 1)

    def test_requires_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(check_sonar_issues.main([]), 2)

    def test_rejects_conflicting_analysis_scopes(self):
        with self.assertRaises(SystemExit):
            check_sonar_issues.main(["--branch", "main", "--pull-request", "42"])

    def test_fails_when_response_total_is_invalid(self):
        with mock.patch.dict(os.environ, {"SONAR_TOKEN": "secret"}, clear=True):
            with mock.patch.object(
                check_sonar_issues.urllib.request,
                "urlopen",
                return_value=self._response("0"),
            ):
                result = check_sonar_issues.main([])

        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
