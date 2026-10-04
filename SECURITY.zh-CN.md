# 安全与隐私维护
n中文 | [English](SECURITY.md)

本仓库发布代码、测试、锁文件、使用文档及安全样例。提交者负责核对来源权限、署名和实际暂存版本。

## 内容范围

| 可进入 Git | 保留受控，不进入公开 Git 树 |
|---|---|
| 实现、测试、脚本、UV 锁文件、安全样例 | 虚拟环境、缓存、构建产物 |
| 公开使用说明、能力与 API 索引 | 作者学习记录、内部任务与发布审计 |
| 模式检查工具和未启用的 Hook 模板 | 原始模型/图像、真实案例、来源清单、日志与会话 |
| 已确认的公开署名 | 凭据、私人邮箱/姓名/主机、本机绝对路径和内部地址 |

忽略规则不会清除已跟踪内容或历史，也不提供加密、访问控制或备份。对图片、PDF、Office、模型、压缩包、LFS 和子模块须另外核查正文、元数据及来源权限；模式扫描不覆盖这些内容。

## 提交前检查

使用已确认的公开别名与 GitHub noreply 署名，只设置本仓库身份，不更改全局身份。环境变量、amend、cherry-pick 和显式作者参数也可能改变实际署名。

精确暂存并阅读差异。使用 PowerShell 7.2+：

```powershell
git status --short
git diff --cached
pwsh -NoProfile -File scripts/Invoke-RepoPrivacy.ps1 -Mode Staged -CommitMessagePath <仓库外提交说明文件> -ReportPath <仓库外报告文件>
pwsh -NoProfile -File scripts/Invoke-RepoPrivacy.ps1 -Mode Index -ReportPath <仓库外报告文件>
pwsh -NoProfile -File scripts/Invoke-RepoPrivacy.ps1 -Mode History -ReportPath <仓库外报告文件>
```

替换占位路径后执行。额外私人标识通过仓库外 JSON 数组和 `PRIVACY_TERMS_FILE` 传入，不能提交该列表。检查器及公开规则位于 `.privacy-tools/`；工具只扫描本地对象，不上传内容。

| 退出码 | 处理 |
|---|---|
| 0 | 本次范围未发现阻断或待审候选；仍需人工核查附件与来源 |
| 1 | 修复阻断项、重新暂存并检查 |
| 2 | 核查准确版本的邮箱、二进制或大文件，记录理由和日期 |
| 3 | 检查未完成；修复环境或配置后重跑 |

Hook 模板默认不启用；启用前检查 `core.hooksPath` 和现有 Hook，不覆盖已有设置。首次公开、新分支或标签推送前检查全部拟发布历史，推送后回读远端内容、署名、许可及可见性。

轻量模式检查不等于完整密钥审计。GitHub secret scanning 和 push protection 可作为额外检查，不能替代本地内容与历史核查。

## 发现泄露

有效凭据先撤销或轮换，再处理内容与历史。保存受控备份和脱敏证据，按明确授权范围实施修复。删除、重建或改写历史后仍须核验旧对象入口；访问失败、缓存清理和所有副本消失是不同结论。

私人标识、密钥、旧敏感提交编号及原始响应不得复制到公开 Issue、PR 或日志。安全问题只提供脱敏说明和可审查的最小复现；内部发布审计留在受控位置。
