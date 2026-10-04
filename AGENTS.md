# Repository collaboration rules

- README.md is the public user entry point. Keep installation, examples and supported boundaries consistent with actual code. Author learning notes, local migration tasks and publication audits stay in ignored internal materials.
- If this is the maintainer workspace and `docs/internal/AGENTS.md` exists, read it before changing internal records or source-acceptance workflows. Never invent author understanding or confirmed engineering parameters.
- Preserve units, explicit axes, thickness definitions, domain meanings and Face/Solid/Compound contracts. Report missing dependencies, unsupported modes, fallback construction and partial fusion explicitly.
- Validate affected behavior with meaningful normal, boundary or failure cases. Do not weaken tolerances or quality gates merely to pass checks. Update API and capability documentation against actual implementation.
- Use the locked UV environment. Keep original projects, source templates and raw evidence read-only; write changes and outputs only in this project.
- Keep raw assets, local configs, internal documents, environments, caches and audit evidence out of public Git history. Ignored files require separate controlled backups.
- Select staged files precisely. Check actual author/committer identity, staged content, commit message and intended history with the privacy tools; save reports outside the repository.
- Do not enable hooks or modify global Git configuration automatically. Preserve existing local hooks.
- Repository deletion, recreation and history replacement require explicit scoped user authorization. Back up and prepare the reviewed publication tree before those actions; verify remote state afterward.
- Report implementation changes, actual verification, commit and evidence locations, and remaining limitations. Historical proofs are not new checkout results.

## 隐私与提交（2026-10 模板更新）

以下来自母库《隐私检查与提交方案》的协作规则片段（2026-10-03 版），与上文英文规则并存；冲突时以更严格者为准。

- 开始任务时确认仓库可见性、许可证、默认分支以及本轮拟发布范围。
- 使用公开账号别名和已确认的 GitHub noreply 邮箱；检查实际作者和提交者身份。
- 不提交真实凭据、私人联系信息、本机身份路径、内部访问地址、原始 AI 会话或未脱敏的审计记录。
- 示例使用相对路径、环境变量或明确占位符；脱敏后仍需保持代码和文档可理解、可复现。
- 检查完整暂存文件版本及提交说明；首次公开、新分支和发布标签还需检查拟发布历史与附件。
- PDF、Office、图片、压缩数据及 LFS 文件须另做内容和元数据核查；未检查的项目标记为待核验。
- 正常公开的论文署名与文献联系信息经核实后保留，例外须说明来源与范围。
- 检查日志默认不展示匹配原文；私人标识规则、原始备份与旧隐私编号留在仓库外。
- 不通过扩大忽略目录、绕过检查或推送旧受污染历史使检查表面通过。
- 已泄露凭据先撤销或轮换；强推、历史改写和删库重建按明确仓库范围执行，先完成备份和可审查的脱敏副本。
- 验收说明实际扫描范围、人工检查和限制，不以退出码 0 宣称绝对无隐私。
