"""Credential-safe runtime configuration diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.secrets.crypto import SecretDecryptionError
from apps.secrets.keyring import MasterKeyError, load_master_keyring
from apps.secrets.models import SecretCode
from apps.secrets.services import SecretNotConfiguredError, get_secret

from .http_client import (
    ExternalHttpConfigurationError,
    ExternalHttpRequestError,
    create_http_client,
    validate_proxy_url,
)
from .models import SystemConfiguration


@dataclass(frozen=True, slots=True)
class DiagnosticResult:
    name: str
    status: str
    detail: str


_OK = "ok"
_WARNING = "warning"
_ERROR = "error"


def _master_key_result() -> DiagnosticResult:
    try:
        keyring = load_master_keyring(settings.QUOTARADAR_MASTER_KEY_FILE)
    except MasterKeyError:
        return DiagnosticResult("master_key", _ERROR, "master key некорректен")
    return DiagnosticResult(
        "master_key",
        _OK,
        f"master key корректен, активная версия: {keyring.active_version}",
    )


def _secret_result(code: SecretCode) -> DiagnosticResult:
    try:
        value = get_secret(code)
    except SecretNotConfiguredError:
        return DiagnosticResult(code.value, _WARNING, "секрет не настроен")
    except SecretDecryptionError:
        return DiagnosticResult(code.value, _ERROR, "секрет не расшифровывается")

    if code == SecretCode.PROXY_URL:
        try:
            validate_proxy_url(value)
        except ExternalHttpConfigurationError:
            return DiagnosticResult(
                code.value, _ERROR, "proxy URL синтаксически некорректен"
            )
    return DiagnosticResult(code.value, _OK, "секрет настроен")


def _system_configuration_result() -> DiagnosticResult:
    try:
        configuration = SystemConfiguration.load()
    except SystemConfiguration.DoesNotExist:
        return DiagnosticResult(
            "system_configuration",
            _ERROR,
            "системная конфигурация отсутствует",
        )

    missing = [
        label
        for label, value in (
            ("llm_provider", configuration.llm_provider),
            ("llm_base_url", configuration.llm_base_url),
            ("llm_model", configuration.llm_model),
        )
        if not value
    ]
    if missing:
        return DiagnosticResult(
            "system_configuration",
            _WARNING,
            "не заполнены параметры: " + ", ".join(missing),
        )
    return DiagnosticResult("system_configuration", _OK, "конфигурация заполнена")


def _proxy_connection_result(test_url: str) -> DiagnosticResult:
    try:
        with create_http_client() as client:
            response = client.head(test_url)
    except (ExternalHttpConfigurationError, ExternalHttpRequestError):
        return DiagnosticResult(
            "proxy_connection",
            _ERROR,
            "внешний запрос через proxy завершился ошибкой",
        )
    return DiagnosticResult(
        "proxy_connection",
        _OK,
        f"внешний запрос через proxy выполнен, HTTP {response.status_code}",
    )


def collect_diagnostics(
    *,
    test_proxy: bool = False,
    test_url: str = "https://example.com/",
) -> list[DiagnosticResult]:
    results = [_master_key_result(), _system_configuration_result()]
    results.extend(_secret_result(code) for code in SecretCode)
    if test_proxy:
        results.append(_proxy_connection_result(test_url))
    return results
