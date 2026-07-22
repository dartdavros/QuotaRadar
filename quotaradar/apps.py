"""App configs for the ``quotaradar`` project package."""

from django.contrib.admin.apps import AdminConfig


class QuotaRadarAdminConfig(AdminConfig):
    """Point ``admin.site`` at the OTP-enforcing admin site."""

    default_site = "quotaradar.admin_site.QuotaRadarAdminSite"
