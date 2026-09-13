"""Admin site requiring OTP verification for every staff login."""

import logging

from two_factor.admin import AdminSiteOTPRequired

logger = logging.getLogger(__name__)


class QuotaRadarAdminSite(AdminSiteOTPRequired):
    """``AdminSite`` that denies the admin until ``user.is_verified()``.

    Subclasses two_factor's ``AdminSiteOTPRequired`` instead of replacing
    ``admin.site``: combined with ``QuotaRadarAdminConfig.default_site`` the
    admin autodiscovery populates this same instance, so the existing
    ``@admin.register(Model)`` calls keep working unchanged.

    The index page carries the health panel (``apps.monitoring.dashboard``):
    every subsystem is checked on each load so the operator sees what is
    broken, and where, without opening a single changelist.
    """

    site_header = "Quota Radar"

    def index(self, request, extra_context=None):
        # Imported here: this module is resolved while the app registry is still loading.
        from apps.monitoring.dashboard import build_dashboard
        from apps.monitoring.dashboard.report import ERROR, Dashboard

        extra_context = dict(extra_context or {})
        try:
            extra_context["dashboard"] = build_dashboard()
        except Exception as exc:  # The admin must stay usable even if the panel cannot be built.
            logger.exception("Health panel could not be built.")
            extra_context["dashboard"] = Dashboard(
                generated_at="", level=ERROR, headline="", checks=[], errors=[],
                failure=f"{type(exc).__name__}: {exc}")
        return super().index(request, extra_context)
