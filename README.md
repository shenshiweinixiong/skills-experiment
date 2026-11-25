# 第四周 OfficeBench 人工多技能编排

本仓库发布本周**自研源码、测试、集成补丁及脱敏汇总**；与先前的 OfficeBench 无技能基线仓库分开。详见[中文阶段报告](<week4-officebench/第四周阶段报告.md>)、[问题清单](<week4-officebench/问题清单.md>)和[逐题证据索引](<week4-officebench/证据索引.csv>)。

- 21 个不同任务有本机 Next HTTP 代理 → Spring 流程入口 → Python 桥接的后测通过记录；其中 13 个有真实无技能失败前测配对，10 个归为可辩护的修复候选。`1-5/2` 的薪酬单位须人工确认。另 3 个是带类型或单位限制的评分兼容，不算无保留修复。
- 冻结的人工结构含 8 个节点和 9 条边；文件/表格操作按条件进入分支，只读语义与选定原生评分并行检查，通过后才提交。测试 49 项，其中 1 项因 Windows 符号链接权限跳过；Java 4 项 JUnit 通过，Next 页面 ESLint 通过。
- [Next 页面补丁](<platform-integration/next/app/officebench-week4/>)及[Spring 流程类补丁](<platform-integration/spring/core-flow/>)仅是本周编写的接入文件，**不是**教师工程完整源码。它们需要教师原项目、对应依赖和本地服务；Spring 使用旧可执行包加隔离编译类覆盖联调，不等于完整 Maven 重新打包或教师技能注册中心原生调度。

## 证据与复现范围

为保护模型运行记录、实验输入和本机配置，`runs/`、`bridge-runs/`、缓存、数据库及私有配置**没有上传**。索引中的这些相对路径是本机审计来源，不是仓库内可打开的文件；因此公开仓库不能独立证明每次前测或重放 21 次后测。要自行复现，需合法获取 OfficeBench 数据、原教师项目和相应依赖，然后设置 `cases.json` 中的 `source` 为本机 OfficeBench 根目录。隐藏参考答案只用于宿主机评分，不能交给执行代理。完整 OfficeBench 官方评测并未在本次验证中运行。

平台截图与原始轨迹未公开；详细交互结果见[脱敏浏览器观测](<week4-officebench/platform-interactive-evidence.txt>)。两道题的题面与评分冲突、一次精确匹配误评分及未修复项见[评分冲突说明](<week4-officebench/新增筛选与评分冲突.md>)。不得把事后筛选出的任务比例称为总体提升率。
