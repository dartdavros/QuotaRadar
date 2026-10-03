#!/usr/bin/env bash
# Update application code in place, retaining production storage and runtime files.
set -euo pipefail

: "${GITHUB_SHA:?GITHUB_SHA is required}"
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 1
deploy_dir=/opt/quotaradar
archive="/tmp/quotaradar-${GITHUB_SHA}.tar.gz"
runtime_services=(web bot worker news-worker news-urgent beat)
runtime_paths=(quotaradar-news-cache celerybeat-schedule celerybeat-schedule.db
  celerybeat-schedule.dat celerybeat-schedule.dir celerybeat-schedule.bak)

sudo test -f "$deploy_dir/.env"
sudo test -f "$deploy_dir/docker/secrets/master.key"
test -f "$archive"
command -v rsync >/dev/null

release_dir=$(mktemp -d "/tmp/quotaradar-release-${GITHUB_SHA}.XXXXXX")
deploy_complete=false
cleanup() {
  status=$?
  sudo rm -rf -- "$release_dir"
  if [ "$status" -eq 0 ] && [ "$deploy_complete" != true ]; then
    echo 'Deployment script ended before completing the release.' >&2
    exit 1
  fi
  exit "$status"
}
trap cleanup EXIT
sudo tar -xzf "$archive" -C "$release_dir"
sudo cp "$deploy_dir/.env" "$release_dir/.env"
sudo cp "$deploy_dir/docker/secrets/master.key" "$release_dir/docker/secrets/master.key"
sudo chmod 0444 "$release_dir/docker/secrets/master.key"

backup_dir="$deploy_dir/backups/deploy-$(date -u +%Y%m%dT%H%M%SZ)-${GITHUB_SHA}"
sudo mkdir -m 700 "$backup_dir"
sudo tar --exclude='./backups' --exclude='./.git' \
  -czf "$backup_dir/source.before.tar.gz" -C "$deploy_dir" .
image_id=$(sudo docker inspect quotaradar-web-1 --format '{{.Image}}')
sudo docker tag "$image_id" "quotaradar:before-${GITHUB_SHA}"
printf '%s\n' "$image_id" | sudo tee "$backup_dir/image-id.before" >/dev/null

cd "$release_dir"
sudo docker compose -p quotaradar config --quiet
sudo docker compose -p quotaradar build web
sudo docker compose -p quotaradar run --rm --no-deps --pull never \
  --entrypoint python web manage.py check < /dev/null

cd "$deploy_dir"
# Wait for warm worker shutdown and bot long polling; never force-kill them.
sudo docker compose stop --timeout -1 "${runtime_services[@]}"
for service in "${runtime_services[@]}"; do
  container=$(sudo docker compose ps -aq "$service")
  sudo mkdir "$backup_dir/$service"
  # Snapshot after stopping, including cache created by the last running task.
  sudo docker cp -a "$container:/tmp/." "$backup_dir/$service/"
done

# Keep credentials, backups and existing host storage at their current paths.
sudo rsync -a --delete \
  --exclude='/.env' --exclude='/docker/secrets/*.key' \
  --exclude='/backups/' --exclude='/media/' --exclude='/staticfiles/' \
  --exclude='/.git/' "$release_dir/" "$deploy_dir/"
sudo docker compose up --no-deps --no-build --pull never \
  --abort-on-container-exit --exit-code-from init init < /dev/null
sudo docker compose up --no-start --no-deps --no-build --pull never "${runtime_services[@]}" < /dev/null
runtime_containers=()
for service in "${runtime_services[@]}"; do
  container=$(sudo docker compose ps -aq "$service")
  runtime_containers+=("$container")
  for path in "${runtime_paths[@]}"; do
    if sudo test -e "$backup_dir/$service/$path"; then
      sudo docker cp -a "$backup_dir/$service/$path" "$container:/tmp/"
    fi
  done
done
sudo docker start "${runtime_containers[@]}"

web_container=$(sudo docker compose ps -q web)
for _ in $(seq 1 90); do
  health=$(sudo docker inspect --format '{{.State.Health.Status}}' "$web_container")
  if [ "$health" = healthy ]; then
    sudo docker compose ps
    sudo docker compose exec -T web python manage.py diagnose_configuration < /dev/null
    rm -f -- "$archive"
    echo "Deployed $GITHUB_SHA; rollback files retained in $backup_dir"
    deploy_complete=true
    exit 0
  fi
  sleep 2
done
sudo docker compose logs --tail 100 web init
echo "Web health check failed; rollback files retained in $backup_dir" >&2
exit 1
