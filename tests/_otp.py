"""Test helpers for two-factor authenticated admin requests.

The admin now requires OTP verification (``QuotaRadarAdminSite`` extends
``AdminSiteOTPRequired``), so ``client.force_login(user)`` alone is rejected
with a redirect to the login flow. These helpers authenticate a test user and
mark the session as OTP-verified, mirroring what
``django_otp.middleware.OTPMiddleware`` reads on a real successful token
check, so admin unit tests can exercise the change/changelist views without
stepping through the full two-factor wizard.
"""

from __future__ import annotations

from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice


def force_login_verified(client, user) -> TOTPDevice:
    """Authenticate ``user`` on ``client`` and mark the session OTP-verified.

    Stores the device id in the session under django-otp's key so that
    ``OTPMiddleware`` re-attaches the device on the next request and
    ``user.is_verified()`` returns ``True``. Returns the created ``TOTPDevice``
    so callers that need it (e.g. backup-token assertions) can use it.
    """
    client.force_login(user)
    device = TOTPDevice.objects.create(user=user, confirmed=True, name="test")
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()
    return device
