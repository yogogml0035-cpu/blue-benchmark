# M0 集成与真实样本验收实施计划

## Ordered checklist

1. 建立合成跨层 fixture 和一键数据库/Worker/API/frontend 测试环境。
2. 运行全量自动化、生成合同和生产构建，修复归属任务问题。
3. 确认真实样本路径只读可用，运行本地导入分类检查。
4. 走通两任务共创、同场景组集、v1 冻结、下载和哈希/泄漏验证。
5. 执行刷新、进程重启、租约回收、projection_pending 和 thread 删除矩阵。
6. 用浏览器完成 desktop/narrow/a11y/错误恢复闭环。
7. 更新 README、配置示例、架构状态和 Trellis specs。
8. 生成最终验收报告，明确已执行、已接受和仍未验证项。

## Validation

```bash
make test
make build
```

真实样本命令必须是显式 opt-in，默认 CI 不发现也不读取用户目录。

## Completion gate

- 两个真实任务形成同一不可变 v1，包和 API 哈希一致。
- 端到端恢复、权限、信息隔离和视觉验收均有机械证据。
- README 与源码命令一致，Trellis specs 不再描述内存 Walking Skeleton。
