from django.test import SimpleTestCase

from apps.analysis.reset_signals import (
    CODEX_RESET_AUTHOR_ID, has_reset_exclusions, needs_reset_review,
)
from apps.analysis.series_reset import classify_series_reset
from apps.sources.models import Source, SourcePost

# Real @thsottiaux posts from production, keyed by X post ID.
DAY_17 = ("2113162277688070445", (
    "Day 17/ Bet you thought we forgot, but no, it’s reset day today.\n"
    "Also good time to remind you to get Daybreak Blue access, it only takes 15 mins "
    "and you don’t want to have to do it in the middle of an incident."
))
SIDE_OF_RESET = ("2109873287853707513",
                 "What would you like with your side of reset? It's done. https://t.co/gpNaB6otgy")
MISSED_RESET = ("2106233145163141249", (
    "Seeing some reports that the Pro 500 didn’t get the reset as expected earlier. "
    "Investigating and will make up for it"
))
NO_RESET_GIVEN = ("2105672058269212820", (
    "Because usage on your primary dot is virtually unlimited at the moment, "
    "I can’t really give a reset. I need to come up with something new fast."
))


class ResetSignalTests(SimpleTestCase):
    def post(self, text, username="thsottiaux", provider="openai"):
        return SourcePost(source=Source(username=username, provider=provider), text=text)

    def test_direct_mass_reset_announcements_need_review(self):
        for text in (
            "Global reset by EOD. May the tokens do good things for you.",
            "We will reset usage limits for all paid users tomorrow.",
            "Codex limits have been reset for everyone.",
        ):
            with self.subTest(text=text):
                self.assertTrue(needs_reset_review(self.post(text)))
        self.assertTrue(needs_reset_review(self.post(
            "Claude Code usage limits have been reset for all users.",
            username="ClaudeDevs", provider="anthropic",
        )))

    def test_reset_alone_and_non_quota_cases_do_not_trigger_review(self):
        for text in (
            "Reset",
            "We reset all Git branches to fix token usage.",
            "Global API rate limits reset by EOD.",
            "All TPM limits reset by EOD.",
            "HTTP 429: all limits reset by EOD.",
            "My account limits have been reset.",
            "We reset all limits for one account.",
            "Reset all infrastructure usage counters.",
            "Reset all settings to reduce token usage.",
            "Could we reset limits for everyone?",
            "We will not reset limits for all users.",
            "I hope all users get their limits reset.",
        ):
            with self.subTest(text=text):
                self.assertFalse(needs_reset_review(self.post(text)))

    def test_untrusted_source_or_quoted_only_claim_is_not_a_signal(self):
        text = "Global reset by EOD. May the tokens do good things for you."
        self.assertFalse(needs_reset_review(self.post(text, username="other")))
        post = self.post("Thanks!")
        post.normalized_text = "Thanks!\n\nReply parent:\n" + text
        self.assertFalse(needs_reset_review(post))


class VerifiedAuthorResetSignalTests(SimpleTestCase):
    def post(self, real_post):
        external_id, text = real_post
        return SourcePost(
            source=Source(username="thsottiaux", provider="openai", x_user_id=CODEX_RESET_AUTHOR_ID),
            external_id=external_id, text=text, normalized_text=text,
            raw_data={"post": {"id": external_id, "author_id": CODEX_RESET_AUTHOR_ID}},
        )

    def test_rebutted_negation_is_not_a_negation(self):
        self.assertFalse(has_reset_exclusions(DAY_17[1]))

    def test_typographic_apostrophe_negations_are_detected(self):
        for real_post in (MISSED_RESET, NO_RESET_GIVEN):
            with self.subTest(post=real_post[0]):
                self.assertTrue(has_reset_exclusions(real_post[1]))

    def test_questions_and_negations_go_to_review(self):
        for real_post in (DAY_17, SIDE_OF_RESET, MISSED_RESET, NO_RESET_GIVEN):
            with self.subTest(post=real_post[0]):
                self.assertTrue(needs_reset_review(self.post(real_post)))

    def test_technical_resets_still_skip_review(self):
        for text in (
            "We reset all Git branches.", "Global API rate limits reset by EOD.",
            "Reset all settings.", "My account limits have been reset.",
        ):
            with self.subTest(text=text):
                self.assertFalse(needs_reset_review(self.post(("2113162277688070445", text))))

    def test_free_form_day_post_is_left_to_the_model(self):
        self.assertIsNone(classify_series_reset(self.post(DAY_17)))
