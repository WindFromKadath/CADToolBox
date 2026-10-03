# CADToolBox

Python CAD 工具与建模方法库，提供 STEP/DXF 处理、参数化几何、二维约束求解和受控图像轮廓处理。通过明确的单位、轴、参数来源和质量检查，将输入连接到可验证的几何输出。

当前版本：`0.1.0`。API 和配置格式仍在发展中。长度统一为 mm，角度为 rad；明确区分 Face、Solid、Compound 及预期实体数。

## 能做什么

| 功能 | 当前支持 |
|---|---|
| 文件与质量检查 | STEP 导入、导出和回读；轴向测量；实体数、短边和退化检查 |
| DXF 轮廓 | 闭合 XY 轮廓，支持 LINE、ARC、CIRCLE、带 bulge 的二维多段线、SPLINE 和 ELLIPSE |
| 参数化构造 | 旋转、拉伸、圆弧/角度律叶片、域裁剪、阵列与融合 |
| 曲面与叶片 | 四边界 Coons、受支持的二维扭转场、预算内拟合与共享边界封闭 |
| 二维约束求解 | 独立进程运行 slvs；报告自由度、冲突和残差；求解坐标驱动 CAD/DXF |
| 图像处理 | 受控单色/三色轮廓；像素线、圆、弧候选及 JSON/PNG/SVG 输出 |
| 建模方法 | 参数来源、域选择、拟合预算、构造策略及失败处理的适用条件 |

详细能力与接口见 [工具/方法目录](docs/project-status.json)、[使用说明](docs/USAGE.md) 和 [API 索引](docs/api-index.json)。

## 安装与首次运行

需要 Git、uv 和 PowerShell。当前验证环境为 Windows、Python 3.13；依赖版本由 `uv.lock` 固定。项目脚本将环境与缓存保存在项目目录内。

```powershell
git clone https://github.com/WindFromKadath/CADToolBox.git
Set-Location -LiteralPath 'CADToolBox'
.\scripts\uv.ps1 python install 3.13 --no-bin --no-registry
.\scripts\uv.ps1 sync --locked --managed-python
.\scripts\uv.ps1 run --locked cadtoolbox --help
.\scripts\uv.ps1 run --locked cadtoolbox demo-io --output artifacts/my-first-demo
```

`demo-io` 自动生成合成 DXF 和 STEP，检查解析体积并回读结果。输出目录必须是新目录；再次运行时更换目录名。CLI 返回 JSON 报告。

运行公开求解样例：

```powershell
.\scripts\uv.ps1 run --locked cadtoolbox solve-sketch examples/solver-case.json
.\scripts\uv.ps1 run --locked cadtoolbox build-solved-profile examples/solver-case.json --output artifacts/my-solved-profile
```

图像样例生成、Python API、配置字段和失败排查见 [使用说明](docs/USAGE.md)。

## 运行回归

```powershell
.\scripts\uv.ps1 run --locked python scripts/prepare_examples.py
.\scripts\uv.ps1 run --locked pytest -q
```

准备脚本仅在配置缺失时安装安全测试夹具，保留已有配置。测试使用合成数据；真实工程输入和来源验收证据不随仓库分发。

## 使用边界

- DXF 当前处理闭合 XY 轮廓，未支持跨层嵌套孔的自动解释。
- 叶片支持弧长或弦长厚度；法向等厚偏移、任意 STEP 底面参数化和全局自交证明尚未支持。圆角边识别适用于已声明的两端转子特征。
- 求解器只覆盖已实现的实体与约束，不具备完整工程图语义编译能力。
- 图像候选保留像素单位与待确认状态，不自动变成工程尺寸；通用 OCR、完整尺寸链和任意图纸到 STEP 尚未实现。
- `list-tools`、`list-methods` 和来源检查依赖维护者的本地清单。公开使用者可查阅静态工具/方法目录，并使用独立 CLI、API 和安全样例。

调用者需要提供明确的单位、轴、标定和参数来源。缺失、冲突或未批准的假设会阻止确定几何；几何检查通过也不代替工程设计确认。

## 维护与许可

贡献和验收要求见 [维护指南](docs/MAINTENANCE.md)，提交范围与隐私检查见 [安全声明](SECURITY.md)。原始模型、图像、私有配置、内部学习记录、环境、缓存和生成产物不进入公开版本管理。

项目代码采用 [MIT 许可证](LICENSE)。第三方依赖及输入数据遵循各自的许可和来源权限。
