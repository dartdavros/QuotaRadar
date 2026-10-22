from django.test import TestCase

from apps.monitoring.normalization import normalize_source_post
from apps.sources.models import Source


class ReplyContextTests(TestCase):
    def setUp(self):
        self.source = Source.objects.get(username="thsottiaux")
        self.post = {
            "id": "2109045392684032299", "author_id": "1953337039510003712",
            "text": "Global reset by EOD. May the tokens do good things for you.",
            "created_at": "2026-10-10T22:16:20.000Z",
            "referenced_tweets": [{"id": "2109045220411351517", "type": "replied_to"}],
        }
        self.parent = {
            "id": "2109045220411351517", "author_id": "1953337039510003712",
            "text": "Day 6/ Reset",
        }
        self.includes = {
            "tweets": [self.parent],
            "users": [{"id": "1953337039510003712", "username": "thsottiaux"}],
        }

    def normalize(self):
        return normalize_source_post(source=self.source, post=self.post, includes=self.includes)

    def test_real_reply_keeps_own_text_and_labels_parent_author(self):
        result = self.normalize()
        self.assertEqual(result.text, self.post["text"])
        self.assertIn("Reply parent (@thsottiaux; same author):\nDay 6/ Reset", result.normalized_text)
        self.assertEqual(result.raw_data["resolved_context"]["reply_parents"], [self.parent])
        self.assertEqual(result.raw_data["resolved_context"]["quoted_tweets"], [])

    def test_other_authors_parent_is_not_attributed_to_source(self):
        self.parent["author_id"] = "other-id"
        self.includes["users"].append({"id": "other-id", "username": "other"})
        self.assertIn("Reply parent (@other; different or unknown author)", self.normalize().normalized_text)

    def test_missing_parent_does_not_invent_context(self):
        self.includes["tweets"] = []
        result = self.normalize()
        self.assertEqual(result.normalized_text, self.post["text"])
        self.assertEqual(result.raw_data["resolved_context"]["reply_parents"], [])

    def test_missing_author_ids_do_not_claim_same_author(self):
        self.post.pop("author_id")
        self.parent.pop("author_id")
        self.assertIn("author_id: unknown; different or unknown author", self.normalize().normalized_text)

    def test_parent_full_text_urls_article_and_media_are_preserved(self):
        self.parent["note_tweet"] = {
            "text": "Full parent https://t.co/limits",
            "entities": {"urls": [{"url": "https://t.co/limits", "expanded_url": "https://example.com/limits"}]},
        }
        self.parent["article"] = {"title": "Article title", "plain_text": "Article body"}
        self.parent["attachments"] = {"media_keys": ["3_parent"]}
        self.includes["media"] = [{"media_key": "3_parent", "alt_text": "Quota chart"}]
        result = self.normalize()
        for text in ("Full parent https://example.com/limits", "Article title", "Article body", "Quota chart"):
            self.assertIn(text, result.normalized_text)
        self.assertEqual(result.raw_data["resolved_context"]["attached_media"][0]["media_key"], "3_parent")
