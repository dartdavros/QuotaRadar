FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system quotaradar \
    && useradd --system --gid quotaradar --create-home quotaradar

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install --requirement requirements.txt

COPY --chown=quotaradar:quotaradar . .
RUN chmod 0755 /app/docker/entrypoint.sh \
    && mkdir -p /app/staticfiles \
    && chown -R quotaradar:quotaradar /app/staticfiles

USER quotaradar

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]
