from django.test import SimpleTestCase

from apps.analysis.reset_signals import CODEX_RESET_AUTHOR_ID, needs_reset_review
from apps.analysis.series_reset import SERIES_RESET_MODEL, classify_series_reset
from apps.sources.models import Source, SourcePost


class SeriesResetTests(SimpleTestCase):
    def post(self, text):
        return SourcePost(
            source=Source(username="thsottiaux", provider="openai", x_user_id=CODEX_RESET_AUTHOR_ID),
            external_id="2110595484180214059", text=text, normalized_text=text,
            raw_data={"post": {"id": "2110595484180214059", "author_id": CODEX_RESET_AUTHOR_ID}},
        )

    def test_actual_days_6_8_10_are_classified_without_model_judgment(self):
        for day, text in (
            ("6", "Day 6/ Reset"), ("8", "Day 8/ Reset"),
            ("10", "The reports of my reset button being lost are greatly exaggerated\nDay 10/ Reset"),
        ):
            with self.subTest(day=day):
                response = classify_series_reset(self.post(text))
                self.assertIsNotNone(response)
                self.assertTrue(response.payload.is_relevant)
                self.assertEqual(response.payload.event_type, "quota_reset")
                self.assertEqual(response.payload.message_ru, f"Объявлен сброс лимитов Codex — день {day}.")
                self.assertEqual(response.raw_response["classification"]["rule"], SERIES_RESET_MODEL)

    def test_identity_is_verified_against_raw_author_and_source_id(self):
        for field in ("source_id", "raw_author", "raw_id", "provider", "retweet"):
            with self.subTest(field=field):
                post = self.post("Day 10/ Reset")
                if field == "source_id": post.source.x_user_id = "other"
                if field == "raw_author": post.raw_data["post"]["author_id"] = "other"
                if field == "raw_id": post.raw_data["post"]["id"] = "other"
                if field == "provider": post.source.provider = "anthropic"
                if field == "retweet": post.raw_data["post"]["referenced_tweets"] = [{"type": "retweeted"}]
                self.assertIsNone(classify_series_reset(post))

    def test_parent_or_quote_alone_does_not_trigger_rule(self):
        post = self.post("Thanks!")
        post.normalized_text += "\n\nReply parent:\nDay 10/ Reset"
        post.raw_data["includes"] = {"tweets": [{"text": "Day 10/ Reset", "author_id": CODEX_RESET_AUTHOR_ID}]}
        self.assertIsNone(classify_series_reset(post))

    def test_rule_excludes_questions_negations_technical_and_ambiguous_context(self):
        for text in (
            "Day 10/ Reset?", "No reset today.\nDay 10/ Reset",
            "API limits: Day 10/ Reset", "Git reset\nDay 10/ Reset",
            "Reset settings\nDay 10/ Reset", "My account reset\nDay 10/ Reset",
            "Example:\nDay 10/ Reset", "> Day 10/ Reset",
            "```\nDay 10/ Reset\n```", "Cancelled\nDay 10/ Reset",
            "Tomorrow\nDay 10/ Reset", "Global reset landing by EOD\nDay 10/ Reset",
            "Day 10/ Reset\nDay 11/ Reset", "Day 0/ Reset", "Day 10/ Reset is an example",
        ):
            with self.subTest(text=text):
                self.assertIsNone(classify_series_reset(self.post(text)))

    def test_verified_reset_posts_no_longer_need_quota_keywords_for_review(self):
        for text in ("Day 6/ Reset", "Day 8/ Reset", "Global reset landing by EOD PST time. Enjoy"):
            with self.subTest(text=text):
                self.assertTrue(needs_reset_review(self.post(text)))

    def test_other_sources_keep_previous_review_criteria(self):
        post = self.post("Global reset landing by EOD PST time. Enjoy")
        post.source.username = "OpenAIDevs"
        post.source.x_user_id = post.raw_data["post"]["author_id"] = "1001"
        self.assertFalse(needs_reset_review(post))
