# 白黄主题与收件箱自定义标签

- 主题：先试过黄主色偏怪；改为白底 + 墨黑主控（`primary`/`seed` = ink），黄色仅作点缀（星标、未读点、标签、登录侧栏图标）；画布近中性浅灰。
- 后端：迁移 9 `labels` / `item_labels`；REST `GET/POST /api/labels`、`PUT/DELETE /api/labels/{id}`、`PUT /api/items/{id}/labels`；feed `filter=labeled&label_id=`；事项带 `label_ids`。
- 前端：收件箱可新建/筛选/长按删除标签；详情可给事项打标签；星标「收藏」保留。
- 验证：migration 9 已应用；demo 账号可创建「复习」标签；`dart analyze` 相关文件通过。
