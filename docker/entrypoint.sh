#!/bin/sh
set -eu

run_checks() {
    python manage.py check
    python manage.py check_dependencies
}

case "${1:-}" in
    web)
        python manage.py migrate --noinput
        python manage.py collectstatic --noinput
        run_checks
        exec gunicorn quotaradar.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers 2 \
            --access-logfile - \
            --error-logfile -
        ;;
    bot)
        run_checks
        exec python manage.py runbot
        ;;
    worker)
        run_checks
        exec celery -A quotaradar worker --loglevel=INFO
        ;;
    beat)
        run_checks
        exec celery -A quotaradar beat \
            --loglevel=INFO \
            --schedule=/tmp/celerybeat-schedule
        ;;
    *)
        exec "$@"
        ;;
esac
