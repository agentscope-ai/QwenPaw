#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE=${WELDON_ENV_FILE:-"$SCRIPT_DIR/.env"}
COMPOSE_FILE="$SCRIPT_DIR/compose.production.yml"

usage() {
  cat <<'EOF'
用法：deploy/weldon.sh <init|up|down|status|logs|backup|restore>

  init     预检、构建、初始化数据库和应用，然后启动服务
  up       启动已初始化的服务
  down     停止服务，不删除数据
  status   查看容器和应用健康状态
  logs     持续查看应用日志
  backup   创建数据库、文件和密钥的一致性备份
  restore  恢复到空数据根或新实例
EOF
}

fail() {
  echo "WeldonAgent：$*" >&2
  exit 1
}

compose() {
  docker compose \
    --project-name weldonagent \
    --env-file "$ENV_FILE" \
    --file "$COMPOSE_FILE" \
    "$@"
}

read_env_value() {
  key=$1
  value=$(sed -n "s/^[[:space:]]*$key[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | tail -n 1)
  value=${value#\"}
  value=${value%\"}
  value=${value#\'}
  value=${value%\'}
  printf '%s' "$value"
}

preflight() {
  command -v docker >/dev/null 2>&1 || fail "未找到 Docker"
  docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2"
  [ -f "$ENV_FILE" ] || fail "缺少 $ENV_FILE，请复制 .env.production.example 后配置"
  data_root=$(read_env_value WELDON_DATA_ROOT)
  [ -n "$data_root" ] || fail "WELDON_DATA_ROOT 不能为空"
  password=$(read_env_value WELDON_DB_PASSWORD)
  [ "$password" != "REPLACE_WITH_RANDOM_PASSWORD" ] || fail "请设置真实的 WELDON_DB_PASSWORD"
  [ ${#password} -ge 16 ] || fail "WELDON_DB_PASSWORD 长度至少为 16 个字符"
  mkdir -p "$data_root/working" "$data_root/secrets" "$data_root/backups" \
    "$data_root/logs" "$data_root/run" "$data_root/postgres"
  [ -w "$data_root" ] || fail "数据根目录不可写：$data_root"
  chmod 700 "$data_root/secrets" 2>/dev/null || true
  compose config --quiet
}

command_name=${1:-}
[ -n "$command_name" ] || {
  usage
  exit 2
}
shift || true

case "$command_name" in
  init)
    preflight
    compose build agent-init agent-app
    compose up -d agent-pg
    compose --profile init run --rm agent-init
    compose up -d agent-app
    compose ps
    ;;
  up)
    preflight
    compose up -d agent-pg agent-app
    ;;
  down)
    compose down
    ;;
  status)
    compose ps
    compose exec -T agent-app python /app/deploy/runtime_env.py exec -- \
      python -m qwenpaw service --config /app/deploy/service.production.json status
    ;;
  logs)
    compose logs --tail=200 -f agent-app
    ;;
  backup)
    preflight
    compose up -d agent-pg
    compose stop agent-app >/dev/null 2>&1 || true
    if compose --profile maintenance run --rm agent-maintenance backup "$@"; then
      compose up -d agent-app
    else
      status=$?
      compose up -d agent-app || true
      exit "$status"
    fi
    ;;
  restore)
    preflight
    [ "$#" -gt 0 ] || fail "restore 需要 /data/backups 下的备份目录"
    compose up -d agent-pg
    compose stop agent-app >/dev/null 2>&1 || true
    compose --profile maintenance run --rm agent-maintenance restore "$@"
    compose --profile init run --rm agent-init
    compose up -d agent-app
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
