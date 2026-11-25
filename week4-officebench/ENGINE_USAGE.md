# 本地执行引擎与验证入口

`engine.py` 读取人工固定的 `cases.json`（21个不同子任务）和 `structure.json`，在隔离暂存目录运行，不修改原始OfficeBench输入，也不调用模型API。`cases.json` 的 `source` 给出本机OfficeBench路径；换机器时须先准备合法的源任务及相应路径。下列命令从工作区根目录、带有 `openpyxl` 等本项目依赖的Python环境运行：

```bash
python week4-officebench/engine.py plan
python week4-officebench/engine.py plan --case 1-3/2
python week4-officebench/engine.py run --case 1-3/2 --out week4-officebench/runs/single
python week4-officebench/engine.py run-all --out week4-officebench/runs/batch
python -m unittest discover -s week4-officebench -p 'test_*.py' -v
python week4-officebench/build_evidence_index.py
```

每次执行使用新的 `--out` 目录；现有输出不会覆盖。单例在 `<out>/1-3_2/`，`stage/` 保留暂存，守卫通过后产生 `artifact/`，`evidence.json` 记录节点事件、输入/产物SHA-256、选定原生谓词及拒绝原因。`before` 仅是同一输入未修改时的状态，**不是无技能模型失败**；无技能前测应查 `runs/baseline-no-skill/` 与 `runs/regrade-exact/`，平台代理后测查 `bridge-runs/`，配对见[证据索引](<证据索引.csv>)。索引由脚本生成，不手工修改CSV；重建依赖对应原始运行目录仍存在。

本机已观察21个不同任务经 Next HTTP代理→实际Spring流程入口（旧可执行包加隔离编译 `FlowCodeRun` 覆盖）→Python桥接通过；浏览器点击/重载验证见[交互记录](<platform-interactive-evidence.txt>)。这是本机冻结图转发，不是Spring原生注册中心逐技能运行；平台启动依赖本地MySQL及教师工程服务，不能由上述单独的 `engine.py` 命令复现完整链路。Python测试49项、1项Windows符号链接权限跳过；Java 4项JUnit通过，Next路由ESLint通过。完整Maven打包与平台构建未证明，原生选定条件与语义验收不等于完整官方评测。保留私有配置、数据库口令及原始trace于本机，不公开。
