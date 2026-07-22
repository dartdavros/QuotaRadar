"""Root URL configuration: two-factor auth flow and the Django admin.

``two_factor.urls`` exposes ``urlpatterns`` as the legacy ``(pattern_list,
app_namespace)`` 2-tuple, which ``django.urls.checks`` rejects on Django 5.2
(``urls.E004``). We unwrap the pattern list and pass it to ``include`` as an
explicit ``(patterns, app_namespace)`` tuple, which is the supported form and
keeps ``manage.py check`` green.
"""

from django.contrib import admin
from django.urls import include, path

from two_factor import urls as two_factor_urls

two_factor_patterns, two_factor_app_namespace = two_factor_urls.urlpatterns

urlpatterns = [
    path(
        "",
        include(
            (two_factor_patterns, two_factor_app_namespace),
            namespace="two_factor",
        ),
    ),
    path("admin/", admin.site.urls),
]
