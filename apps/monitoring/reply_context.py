"""Resolve X references and label a reply parent's actual author."""

from .normalization_text import entity_urls, expand_urls, extract_article_text, preferred_post_text


def referenced_posts(post, included_posts, reference_type):
    result = []
    seen = set()
    for reference in post.get("referenced_tweets") or []:
        if not isinstance(reference, dict) or reference.get("type") != reference_type:
            continue
        post_id = reference.get("id")
        if isinstance(post_id, str) and post_id in included_posts and post_id not in seen:
            seen.add(post_id)
            result.append(included_posts[post_id])
    return result


def reply_sections(*, parents, post, includes, source) -> list[str]:
    users = {
        user["id"]: user for user in includes.get("users") or []
        if isinstance(user, dict) and isinstance(user.get("id"), str)
    }
    sections = []
    for parent in parents:
        author_id = parent.get("author_id")
        same_author = bool(author_id and author_id == post.get("author_id"))
        username = users.get(author_id, {}).get("username")
        if not username and same_author:
            username = source.username
        author = f"@{username}" if username else f"author_id: {author_id or 'unknown'}"
        identity = "same author" if same_author else "different or unknown author"
        heading = f"Reply parent ({author}; {identity})"
        text = expand_urls(preferred_post_text(parent), entity_urls(parent))
        if text:
            sections.append(f"{heading}:\n{text}")
        article = extract_article_text(parent.get("article"))
        if article:
            sections.append(f"{heading}, article:\n{article}")
    return sections
