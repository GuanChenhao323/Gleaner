#!/bin/sh
# 拾课数据备份（docker compose 的 backup 服务）：每天一次
#   - PostgreSQL：pg_dump 自定义格式（pg_restore 恢复）
#   - 数据卷：扫码传输文件（coredata）与 MQTT Broker 状态（brokerdata）打成 tar.gz
# 备份保留 BACKUP_KEEP_DAYS 天（默认 14）。BACKUP_ONCE=1 时只备份一次就退出（手动备份、测试用）。
set -u
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
mkdir -p /backups
while true; do
  ts="$(date +%Y%m%d-%H%M%S)"
  if pg_dump -h postgres -U gleaner -d gleaner -Fc -f "/backups/gleaner-$ts.dump.tmp"; then
    mv "/backups/gleaner-$ts.dump.tmp" "/backups/gleaner-$ts.dump"
    echo "backup ok: gleaner-$ts.dump ($(du -h "/backups/gleaner-$ts.dump" | cut -f1))"
  else
    rm -f "/backups/gleaner-$ts.dump.tmp"
    echo "backup FAILED: pg_dump" >&2
  fi
  if tar -czf "/backups/files-$ts.tar.gz" -C /data core broker; then
    echo "backup ok: files-$ts.tar.gz"
  else
    echo "backup FAILED: data volumes" >&2
  fi
  find /backups -name 'gleaner-*.dump' -mtime "+$KEEP" -delete
  find /backups -name 'files-*.tar.gz' -mtime "+$KEEP" -delete
  [ "${BACKUP_ONCE:-0}" = "1" ] && exit 0
  sleep "$INTERVAL"
done
