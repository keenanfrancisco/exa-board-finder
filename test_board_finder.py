"""Tests for board discovery; all HTTP traffic is mocked."""

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError


def http_error(status, body=b""):
    return HTTPError("https://example.test", status, "error", None, io.BytesIO(body))


class BoardFinderTests(unittest.TestCase):
    def test_slug_candidates(self):
        import board_finder

        self.assertEqual(
            board_finder.slug_candidates("https://www.machindustries.com/about"),
            ["machindustries"],
        )
        self.assertEqual(
            board_finder.slug_candidates("https://jobs.true-anomaly.com"),
            ["true-anomaly", "trueanomaly"],
        )

    def test_load_known_skips_comments_and_blank_lines(self):
        import board_finder

        with mock.patch.object(Path, "read_text", return_value=(
            "# existing companies\n\n"
            "greenhouse machindustries name=Mach Industries\n"
            "lever true-anomaly name=True Anomaly\n"
        )):
            self.assertEqual(
                board_finder.load_known(Path("known.txt")),
                {("greenhouse", "machindustries"), ("lever", "true-anomaly")},
            )

    @mock.patch("urllib.request.urlopen")
    def test_find_board_uses_lever_after_greenhouse_404(self, urlopen):
        import board_finder

        urlopen.side_effect = [
            http_error(404),
            io.BytesIO(json.dumps([{"id": "1"}, {"id": "2"}, {"id": "3"}]).encode()),
        ]

        self.assertEqual(board_finder.find_board("example"), ("lever", 3))
        self.assertEqual(urlopen.call_count, 2)
        first_request = urlopen.call_args_list[0].args[0]
        second_request = urlopen.call_args_list[1].args[0]
        self.assertIn("boards-api.greenhouse.io", first_request.full_url)
        self.assertIn("api.lever.co", second_request.full_url)
        self.assertEqual(urlopen.call_args_list[0].kwargs["timeout"], 10)

    @mock.patch("urllib.request.urlopen")
    def test_find_board_returns_none_when_all_providers_404(self, urlopen):
        import board_finder

        urlopen.side_effect = [http_error(404), http_error(404), http_error(404)]

        self.assertIsNone(board_finder.find_board("missing"))
        self.assertEqual(urlopen.call_count, 3)

    @mock.patch("urllib.request.urlopen")
    def test_find_board_returns_none_after_one_urlerror_retry(self, urlopen):
        import board_finder

        urlopen.side_effect = [URLError("offline"), URLError("offline")]

        self.assertIsNone(board_finder.find_board("unreachable"))
        self.assertEqual(urlopen.call_count, 2)

    def test_load_api_key_prefers_environment(self):
        import board_finder

        with mock.patch.object(Path, "read_text", return_value="EXA_API_KEY=file-secret\n") as read_text:
            self.assertEqual(
                board_finder.load_api_key(environ={"EXA_API_KEY": "env-secret"}),
                "env-secret",
            )
        read_text.assert_not_called()

    def test_load_api_key_reads_file_after_comments(self):
        import board_finder

        with mock.patch.object(
            Path,
            "read_text",
            return_value="\n# ignored\nOTHER=value\nEXA_API_KEY=file-secret\n",
        ):
            self.assertEqual(
                board_finder.load_api_key(environ={}, config_path=Path("exa.env")),
                "file-secret",
            )

    @mock.patch("urllib.request.urlopen")
    def test_exa_request_uses_company_search_payload(self, urlopen):
        import board_finder

        urlopen.return_value = io.BytesIO(b'{"results": []}')

        self.assertEqual(board_finder._search_exa("robotics companies", 7, "test-secret"), [])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.exa.ai/search")
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            json.loads(request.data),
            {
                "query": "robotics companies",
                "category": "company",
                "numResults": 7,
                "type": "auto",
            },
        )
        headers = {name.lower(): value for name, value in request.header_items()}
        self.assertEqual(headers["x-api-key"], "test-secret")
        self.assertEqual(headers["user-agent"], "exa-board-finder/0.1")
        self.assertEqual(headers["content-type"], "application/json")

    @mock.patch("urllib.request.urlopen")
    def test_exa_http_error_redacts_api_key(self, urlopen):
        import board_finder

        urlopen.side_effect = http_error(400, b"invalid key test-secret")
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"EXA_API_KEY": "test-secret"}, clear=True), \
                mock.patch.object(Path, "read_text", return_value=""), \
                contextlib.redirect_stderr(output):
            status = board_finder.main(["robotics companies"])

        self.assertEqual(status, 1)
        self.assertIn("Exa HTTP 400", output.getvalue())
        self.assertIn("invalid key [REDACTED]", output.getvalue())
        self.assertNotIn("test-secret", output.getvalue())

    def test_missing_api_key_exits_two_without_leaking_a_key(self):
        import board_finder

        output = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(Path, "read_text", side_effect=FileNotFoundError), \
                mock.patch.object(sys, "argv", ["board_finder.py", "test query"]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit) as raised:
                raise SystemExit(board_finder.main())

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("EXA_API_KEY", output.getvalue())
        self.assertNotIn("env-secret", output.getvalue())


    def test_collect_rows_uses_slug_not_job_count(self):
        import board_finder

        with mock.patch.object(board_finder, "find_board", side_effect=lambda s: ("greenhouse", 12) if s == "machindustries" else None):
            rows, paste = board_finder._collect_rows(
                [{"title": "Mach Industries", "url": "https://machindustries.com"}],
                {("greenhouse", "other")},
            )
        self.assertEqual(rows[0][2:6], ("greenhouse", "machindustries", 12, "NEW"))
        self.assertEqual(paste, ["greenhouse machindustries name=Mach Industries"])
        with mock.patch.object(board_finder, "find_board", return_value=("greenhouse", 3)):
            rows, paste = board_finder._collect_rows(
                [{"title": "Mach", "url": "https://machindustries.com"}],
                {("greenhouse", "machindustries")},
            )
        self.assertEqual(rows[0][5], "known")
        self.assertEqual(paste, [])

    def test_slug_candidates_skip_aggregators_and_use_title(self):
        import board_finder

        self.assertEqual(
            board_finder.slug_candidates("https://www.linkedin.com/company/chirp", "CHIRP Robotics Corporation"),
            ["chirprobotics", "chirp-robotics"],
        )
        self.assertIn("nerostechnologies", board_finder.slug_candidates("https://neros.tech", "Neros Technologies"))
        self.assertIn("chaosindustries", board_finder.slug_candidates("https://chaosinc.com", "CHAOS Industries"))

    @mock.patch("urllib.request.urlopen")
    def test_probes_send_custom_user_agent(self, urlopen):
        # Ashby returns 403 to Python's default User-Agent (checked live 2026-11-09).
        import board_finder

        urlopen.side_effect = http_error(404)
        board_finder.find_board("exa")
        self.assertTrue(urlopen.call_args_list)
        for call in urlopen.call_args_list:
            self.assertEqual(call.args[0].get_header("User-agent"), "exa-board-finder/0.1")

if __name__ == "__main__":
    unittest.main()
