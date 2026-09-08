"""Compatibility routing for legacy quota sources and explicit news membership."""
from django.db.models import Q
from .models import Feed, Source

def quota_sources(queryset):
    return queryset.filter(Q(subscriptions__feed=Feed.QUOTA, subscriptions__enabled=True)
                           | Q(subscriptions__isnull=True)).distinct()

def accepts_quota(source_id):
    return quota_sources(Source.objects.filter(pk=source_id)).exists()
