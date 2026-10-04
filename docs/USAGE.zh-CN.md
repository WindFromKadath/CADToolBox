# ToolBox 使用声明与说明
n中文 | [English](USAGE.md)

本工具箱目前供本地开发、几何构造、受控数据处理和验证使用。API、配置与后端依赖仍可能随版本调整。调用者须明确输入单位、轴、参数来源、结果类型与误差门槛；输出报告保留失败和候选状态，不自动确认设计尺寸。

## 环境与基本入口

在项目根目录按 [README](../README.md) 使用 `scripts/uv.ps1` 安装 Python 3.13 并执行 `sync --locked --managed-python`。实际锁定后端见 `uv.lock`；使用本项目环境运行命令。准备安全夹具使用 `python scripts/prepare_examples.py`，再次执行保留已有配置。

| 任务 | 命令（前置 `.\scripts\uv.ps1 run --locked cadtoolbox`） | 输入与输出 |
|---|---|---|
| 查看帮助 | `--help`；子命令加 `--help` | 不依赖原始模型 |
| 最小几何流程 | `demo-io --output artifacts/demo-01` | 自动合成 DXF，解析体积核对，STEP 回读 |
| 检查 STEP | `inspect-step inputs/model.step --kind Solid --axis 0 0 0 1 0 0` | 显式轴测量与导入类型 |
| 回读 STEP | `roundtrip-step inputs/model.step artifacts/rechecked.step --kind Solid` | 默认拒绝覆盖；Compound 必须明确实体数 |
| 检查 DXF | `inspect-dxf inputs/profile.dxf --unit mm --layers PROFILE` | 单位声明一致，选择纯轮廓层 |
| 真求解 | `solve-sketch examples/solver-case.json` | 独立进程，原生状态/自由度/残差 |
| 解驱动实体 | `build-solved-profile examples/solver-case.json --output artifacts/solved-01` | 实际解生成 STEP/DXF；正常样例解析体积 48000 mm³ |
| 曲面叶片 | `build-surface-blade configs/surface-case.json --output artifacts/surface-01` | 本地受控案例；角度场/预算/闭合/回读 |
| 转子 | `build-rotor configs/rotor-case.json --output artifacts/rotor-01` | 本地受控输入；中间审计和最终拓扑门槛 |
| 受控图像实体 | `build-raster-profile artifacts/pixels/single.json --output artifacts/raster-01` | 合成或已审查图像，显式毫米标定 |
| 像素候选 | `extract-image-candidates inputs/candidates.json --output artifacts/candidates-01` | 图像 path+sha256、primitive_settings；JSON/PNG/SVG，不是毫米约束 |
| 清单与来源检查 | `list-tools`、`list-methods`、`show-tool T013`、`show-method M011`、`check --sources` | 维护者本地 configs 清单；新克隆未包含原始来源/证明 |

CLI 为输出设置项目根目录限制，输入可来自受控外部目录。`--root` 是根级选项，须置于子命令之前。场景输出目录必须不存在；重复运行换新的相对目录。`inspect-dxf` 没有输出几何文件。STEP 无法仅凭导入成功证明质量。

```powershell
.\scripts\uv.ps1 run --locked python examples/generate_raster.py --output artifacts/pixels
.\scripts\uv.ps1 run --locked cadtoolbox build-raster-profile artifacts/pixels/single.json --output artifacts/raster-single
.\scripts\uv.ps1 run --locked cadtoolbox build-raster-profile artifacts/pixels/three-regions.json --output artifacts/raster-three
```

`examples/raster-*-case.json` 是回归/标定模板，image_input 中的零摘要与占位图片不能直接通过来源门禁。生成器产生合成像素及真实 SHA-256；替换实际图片须同步更新哈希，并独立核实标定。

## Python API

从新包导入；先导入 `cadtoolbox.geometry` 以设置项目缓存，然后使用后端。实际参数、模块和字段见 [代码抽取 API 索引](api-index.json)，逐项能力边界见 [项目内容记录](project-status.json)。

```python
from pathlib import Path
import cadtoolbox.geometry
import cadquery as cq
from cadtoolbox.contracts import Axis, ShapeExpectation, ShapeKind
from cadtoolbox.geometry.measure import measure
from cadtoolbox.geometry.io import export_step

axis = Axis((0, 0, 0), (1, 0, 0))
solid = cq.Solid.makeCylinder(10, 20, axis.origin_mm, axis.direction)
report = measure(solid, axis)
expected = ShapeExpectation(ShapeKind.SOLID, 1)
export_step(solid, Path('artifacts/api-cylinder.step'), expected)
```

Python API 调用者负责控制写入路径；CLI 的项目根限制不覆盖直接 API 调用。

| 工具 ID | 代码入口 | 使用范围 |
|---|---|---|
| T001/T002/T012 | `geometry.io.load_step/export_step`、`geometry.measure.measure`、`geometry.quality.validate_shape` | 类型/数量、轴向尺寸、拓扑及回读 |
| T003 | `contracts.Parameter/Axis/Frame/Thickness/DomainSpec/QualityPolicy` | 参数来源、单位、右手坐标、厚度和误差合同 |
| T004 | `geometry.io.load_dxf` | 闭合 XY LINE/ARC/CIRCLE/POLYLINE（含 bulge）/SPLINE/ELLIPSE；部分迁移 |
| T005/T009 | `geometry.domains.axisymmetric_channel/projected_channel/material_domain/trim_solid/trim_bspline_face` | 域类型分开，保留全部裁剪分量 |
| T006/T008 | `geometry.parametric`、`theta_fields.build_field`、`twisted_solid.build_twisted_solid` | 受支持底面与场，独立拟合、共享边界封闭 |
| T007 | `geometry.blades.build_radial_blade` | 两圆交点/角度律、弧长或弦长总厚度 |
| T010/T011 | `geometry.assembly`、`rotor_junction` | 两端转子特征识别、严格边数、任意轴阵列与唯一组件融合 |
| T013 | `solver.sketch.solve_sketch`、`solver.model.drive_dimensions`、`workflows.solved_profile` | 正常且完全确定、无冗余、残差合格后生成几何 |
| T014/T015 | `raster.profiles/regions/primitives`、`workflows.raster.run_raster` | 受控轮廓或未确认像素候选 |
| T016 | 各流程的 report 与图像导出 | 部分迁移；交互界面/历史报告其余格式未完成 |

## 配置约定

- 公共求解样例见 `examples/solver-*.json`，原始真实案例保持在本地 configs。`schema_version=1`、`unit=mm`；sketch 中 points/lines/circles/constraints 分别声明 ID、初值、连接关系和约束。尺寸参数含 name/value/unit/source/status，datum 含坐标、source/status。
- `geometry.profile_lines` 指定连续闭合顺序，`hole_circles` 显式列出孔，`extrusion_mm` 与 frame 指定拉伸和局部轴。不得用初始猜值代替尺寸约束；`drive_dimensions` 修改约束值。
- 图像配置使用 image_input 的相对 path 与实际 sha256；source_parameter_references 若提供，也必须读取并匹配真实文件。单色/三色 profile_settings 带明确标定与简化预算；三色名称和相邻关系有固定要求。
- 曲面配置含 base、field、frame、fit、sewing、quality_policy；公式、径向样本、两端规律和 C1 网格按实现约束使用。`step_face` 会报错。源案例不属于公开样例，恢复真实参数前回查私有来源。
- 转子来源配置不能泛化为所有转子；内存建模模式和中间 STEP 审计分开，圆角边数、最终实体数、短边和退化要求保持显式。

来源状态 derived 表示来自说明、计算或受控参照，不代表用户已确认。assumed/missing/conflicting 门禁与字段校验应保留。

## 失败与排查

| 现象 | 检查与处理 |
|---|---|
| 清单命令缺 configs / 证明 | 使用公开静态内容记录；维护者恢复受控本地配置。不要伪造 verified 记录 |
| 找不到依赖或 DLL | 项目 UV `sync --locked`，检查使用 `.venv` 和当前平台；不得把缺依赖记作功能通过 |
| 输出目录已存在 | 换新目录，保留旧报告用于审计；STEP 覆盖仅用明确 `--overwrite` |
| DXF 单位冲突/文字实体 | 核实单位，选择纯轮廓层；不静默去掉未知实体或未闭合边 |
| 欠约束、冲突、冗余 | 读取 DOF、failed_constraint_ids 和残差，补充正确约束；禁止据失败坐标输出确定实体 |
| 哈希不匹配 | 回查输入版本，重新审阅来源；不只替换哈希来掩盖内容变化 |
| 拟合、圆角、融合、回读失败 | 保留 report/中间模型；检查域、厚度、预算、边策略和拓扑，不静默放宽门槛 |
| 候选看起来符合图纸 | 仍须人工确认几何类型、标定与连接；候选评分不是置信概率或设计确认 |

帮助正常返回 0；目录/合同/几何错误通常为 2；check 的校验失败为 1。求解失败或欠约束为 2，编程异常保留堆栈。对外分享报告前按 [隐私声明](../SECURITY.zh-CN.md) 处理路径、配置快照、元数据和原始输入。
