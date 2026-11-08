# Monitoring Module｜设计文档

本目录存放 Campus Radar **信息源定期监测模块**的架构说明；接口契约目前仍保留在 `docs/architecture/`，没有移动。

- [架构设计（architecture.md）](architecture.md)：8 章，含简化总体架构、模块边界、网络方案、Chrome 协作时序、Session 状态机、故障恢复、参数设置。
- [IC-003 监测模块接口契约（上级目录）](../IC-003-monitoring-module.md)：详细 HTTP 接口、跨模块内部契约、状态与迁移规则。
- [OpenAPI 3.1.1（protocols 目录）](../../protocols/monitoring-v1.openapi.yaml)：机器可读接口描述。

**状态：设计阶段。** 本目录的文档不表明功能已上线。首版仅对已保存并启用的校园事项做周期监测；后续新的信息源沿用统一调度和站点适配框架。
