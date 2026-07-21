from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase

from apps.configuration.http_client import ExternalHttpRequestError
from apps.monitoring.tests.helpers import load_json_fixture
from apps.monitoring.x_api import (
    XApiAuthenticationError,
    XApiClient,
    XApiForbiddenError,
    XApiNotFoundError,
    XApiRateLimitError,
    XApiResponseError,
    XApiTemporaryError,
)


class XApiClientTests(SimpleTestCase):
    def test_lookup_and_paginated_timeline_use_saved_fixtures(self) -> None:
        http_client = Mock()
        http_client.get.side_effect = [
            httpx.Response(200, json=load_json_fixture("lookup_users.json")),
            httpx.Response(200, json=load_json_fixture("timeline_page_1.json")),
            httpx.Response(200, json=load_json_fixture("timeline_page_2.json")),
        ]
        client = XApiClient(http_client=http_client, bearer_token="secret-token")

        users = client.lookup_users(["OpenAIDevs", "ClaudeDevs"])
        pages = list(
            client.iter_user_posts(
                "1001",
                since_id="99",
                max_results=5,
            )
        )

        self.assertEqual(users["openaidevs"], "1001")
        self.assertEqual(users["claudedevs"], "2002")
        self.assertEqual(len(pages), 2)
        first_timeline_call = http_client.get.call_args_list[1]
        second_timeline_call = http_client.get.call_args_list[2]
        self.assertEqual(first_timeline_call.kwargs["params"]["since_id"], "99")
        self.assertEqual(first_timeline_call.kwargs["params"]["max_results"], 5)
        self.assertEqual(first_timeline_call.kwargs["params"]["exclude"], "retweets")
        self.assertNotIn("pagination_token", first_timeline_call.kwargs["params"])
        self.assertEqual(
            second_timeline_call.kwargs["params"]["pagination_token"],
            "page-two-token",
        )
        self.assertIn(
            "note_tweet", first_timeline_call.kwargs["params"]["tweet.fields"]
        )
        self.assertIn(
            "attachments.media_keys",
            first_timeline_call.kwargs["params"]["expansions"],
        )
        for request_call in http_client.get.call_args_list:
            self.assertEqual(
                request_call.kwargs["headers"]["Authorization"],
                "Bearer secret-token",
            )

    @patch("apps.monitoring.x_api.get_secret", return_value="secret-token")
    @patch("apps.monitoring.x_api.create_http_client")
    def test_uses_only_common_proxy_http_factory(
        self,
        create_http_client: Mock,
        get_secret: Mock,
    ) -> None:
        XApiClient()

        get_secret.assert_called_once()
        create_http_client.assert_called_once_with(timeout_seconds=30)

    def test_429_exposes_safe_reset_delay(self) -> None:
        http_client = Mock()
        http_client.get.return_value = httpx.Response(
            429,
            headers={"x-rate-limit-reset": "200"},
            json={"errors": [{"message": "rate limit"}]},
        )
        client = XApiClient(http_client=http_client, bearer_token="secret-token")

        with self.assertRaises(XApiRateLimitError) as context:
            client.lookup_users(["OpenAIDevs"])

        self.assertEqual(context.exception.retry_after_seconds(now=150), 51)
        self.assertNotIn("secret-token", str(context.exception))

    def test_5xx_is_temporary_without_response_body(self) -> None:
        http_client = Mock()
        http_client.get.return_value = httpx.Response(
            503,
            json={"secret": "response-body-must-not-leak"},
        )
        client = XApiClient(http_client=http_client, bearer_token="secret-token")

        with self.assertRaises(XApiTemporaryError) as context:
            client.lookup_users(["OpenAIDevs"])

        self.assertNotIn("response-body-must-not-leak", str(context.exception))

    def test_permanent_http_errors_have_specific_safe_types(self) -> None:
        cases = (
            (401, XApiAuthenticationError),
            (403, XApiForbiddenError),
            (404, XApiNotFoundError),
        )
        for status_code, exception_type in cases:
            with self.subTest(status_code=status_code):
                http_client = Mock()
                http_client.get.return_value = httpx.Response(
                    status_code,
                    json={"detail": "must-not-be-copied"},
                )
                client = XApiClient(
                    http_client=http_client,
                    bearer_token="secret-token",
                )

                with self.assertRaises(exception_type) as context:
                    client.lookup_users(["OpenAIDevs"])

                self.assertNotIn("must-not-be-copied", str(context.exception))
                self.assertNotIn("secret-token", str(context.exception))

    def test_proxy_transport_failure_is_temporary_and_sanitized(self) -> None:
        http_client = Mock()
        http_client.get.side_effect = ExternalHttpRequestError(
            "External HTTP request failed."
        )
        client = XApiClient(http_client=http_client, bearer_token="secret-token")

        with self.assertRaises(XApiTemporaryError) as context:
            client.lookup_users(["OpenAIDevs"])

        self.assertEqual(str(context.exception), "X API request failed.")

    def test_repeated_pagination_token_fails_instead_of_looping(self) -> None:
        page = load_json_fixture("timeline_page_1.json")
        http_client = Mock()
        http_client.get.side_effect = [
            httpx.Response(200, json=page),
            httpx.Response(200, json=page),
        ]
        client = XApiClient(http_client=http_client, bearer_token="secret-token")

        with self.assertRaises(XApiResponseError):
            list(
                client.iter_user_posts(
                    "1001",
                    since_id="99",
                    max_results=5,
                )
            )

        self.assertEqual(http_client.get.call_count, 2)

    def test_page_limit_stops_bootstrap_without_following_next_token(self) -> None:
        http_client = Mock()
        http_client.get.return_value = httpx.Response(
            200,
            json=load_json_fixture("timeline_page_1.json"),
        )
        client = XApiClient(http_client=http_client, bearer_token="secret-token")

        pages = list(
            client.iter_user_posts(
                "1001",
                since_id=None,
                max_results=10,
                max_pages=1,
            )
        )

        self.assertEqual(len(pages), 1)
        self.assertEqual(http_client.get.call_count, 1)
        params = http_client.get.call_args.kwargs["params"]
        self.assertEqual(params["max_results"], 10)
        self.assertNotIn("since_id", params)
        self.assertNotIn("pagination_token", params)

    def test_rejects_timeline_page_size_below_x_minimum(self) -> None:
        client = XApiClient(http_client=Mock(), bearer_token="secret-token")

        with self.assertRaisesRegex(ValueError, "between 5 and 100"):
            list(
                client.iter_user_posts(
                    "1001",
                    since_id="99",
                    max_results=3,
                )
            )
