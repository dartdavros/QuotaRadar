"""Admin site requiring OTP verification for every staff login."""

from two_factor.admin import AdminSiteOTPRequired


class QuotaRadarAdminSite(AdminSiteOTPRequired):
    """``AdminSite`` that denies the admin until ``user.is_verified()``.

    Subclasses two_factor's ``AdminSiteOTPRequired`` instead of replacing
    ``admin.site``: combined with ``QuotaRadarAdminConfig.default_site`` the
    admin autodiscovery populates this same instance, so the existing
    ``@admin.register(Model)`` calls keep working unchanged.
    """
