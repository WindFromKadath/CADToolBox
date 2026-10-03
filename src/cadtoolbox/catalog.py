"""Read-only catalog validation; never import legacy source modules."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path, PurePosixPath

TASK_FIELDS = ["id", "requirement", "risk", "acceptance", "check_command", "status", "evidence", "verified_revision", "verified_at"]


class CatalogError(ValueError):
    pass


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"无法读取 {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CatalogError(f"{path.name} 必须为 schema_version=1 的 JSON 对象")
    return data


def load_collection(root: Path, kind: str) -> list[dict]:
    if kind not in {"tool", "method"}:
        raise CatalogError(f"未知清单类型: {kind}")
    data = load_json(root / "configs" / f"{kind}-catalog.json")
    values = data.get(kind + "s")
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise CatalogError(f"{kind} 清单必须是对象数组")
    return values


def get_item(root: Path, kind: str, item_id: str) -> dict:
    matches = [item for item in load_collection(root, kind) if item.get("id") == item_id]
    if len(matches) != 1:
        raise CatalogError(f"未找到唯一的 {kind} ID: {item_id}")
    return matches[0]


def _index(values: list[dict], label: str) -> dict[str, dict]:
    if not isinstance(values, list) or not all(isinstance(v, dict) for v in values):
        raise CatalogError(f"{label} 必须为对象数组")
    result = {}
    for item in values:
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in result:
            raise CatalogError(f"{label} 的 ID 为空或重复: {item_id}")
        result[item_id] = item
    return result


def _inside(base: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise CatalogError("相对路径为空")
    portable = PurePosixPath(relative.replace("\\", "/"))
    if portable.is_absolute() or ".." in portable.parts or ":" in relative:
        raise CatalogError(f"需要目录内的相对路径: {relative}")
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        raise CatalogError(f"路径越出预期目录: {relative}")
    return path


def validate_project(root: Path, *, check_sources: bool = False) -> dict:
    root = root.resolve()
    errors = []
    checks = []
    counts = {}
    source_results = []
    required = ["README.md", "AGENTS.md", "work-items.csv", "pyproject.toml", "src/cadtoolbox/cli.py", "scripts/project_cli.py", "scripts/verify_bootstrap.py", "tests", "configs", "artifacts"]
    for name in required:
        if not (root / name).exists():
            errors.append(f"缺少项目入口或目录: {name}")
    for name in ["README.md", "AGENTS.md", "work-items.csv"]:
        p = root / name
        if p.is_file() and "{{" in p.read_text(encoding="utf-8-sig"):
            errors.append(f"仍有未替换的模板字段: {name}")
    checks.append("project_structure_and_template_fields")
    try:
        project = load_json(root / "configs/project.json")
        sources = load_json(root / "configs/source-catalog.json")
        projects = _index(sources.get("projects"), "来源项目")
        source_index = _index(sources.get("files"), "来源文件")
        tools = _index(load_collection(root, "tool"), "工具")
        methods = _index(load_collection(root, "method"), "方法")
        counts = {"source_projects":len(projects), "source_files":len(source_index), "tools":len(tools), "methods":len(methods)}
        with (root / "work-items.csv").open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != TASK_FIELDS:
                errors.append("任务表字段与工程模板不一致")
            task_index = _index(list(reader), "任务")
        for task in task_index.values():
            if task.get("status") not in {"todo", "doing", "blocked", "done"}:
                errors.append(f"{task['id']} 任务状态无效")
            if task.get("status") == "done":
                if not task.get("verified_revision") or not task.get("verified_at"):
                    errors.append(f"{task['id']} 完成状态缺少版本/日期")
                if not _inside(root, task.get("evidence", "")).is_file():
                    errors.append(f"{task['id']} 完成状态缺少实际证据")
        checks.append("work_items_and_completion_evidence")
        for source in source_index.values():
            sid = source['id']
            pid = source.get("project_id")
            if pid not in projects:
                raise CatalogError(f"{sid} 引用了未知来源项目: {pid}")
            if source.get("evidence_level") != "static_source_only" or source.get("runtime_verified") is not False:
                errors.append(f"{sid} 不应把本次静态读取声明为运行验证")
            digest = source.get("sha256", "")
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                errors.append(f"{sid} 来源 SHA-256 无效")
            path = _inside(Path(projects[pid]["root"]), source.get("relative_path", ""))
            if check_sources:
                if not path.is_file():
                    source_results.append({"id":sid,"match":False,"reason":"missing"})
                    errors.append(f"{sid} 来源文件缺失: {path}")
                else:
                    actual = hashlib.sha256(path.read_bytes()).hexdigest()
                    match = actual == digest
                    source_results.append({"id":sid,"match":match,"sha256":actual})
                    if not match:
                        errors.append(f"{sid} 来源文件已变化，需重新审阅: {path}")
        for group, label in [(tools,"工具"),(methods,"方法")]:
            for item in group.values():
                refs = item.get("source_ids")
                if not isinstance(refs,list) or not refs or any(ref not in source_index for ref in refs):
                    errors.append(f"{item['id']} 的来源引用无效")
                if not isinstance(item.get("name"),str) or not item['name'].strip():
                    errors.append(f"{label}名称为空: {item['id']}")
        for item in tools.values():
            status = item.get("implementation_status")
            if status not in {"planned", "ported", "verified"}:
                errors.append(f"{item['id']} 工具状态无效")
            if item.get("work_item") not in task_index:
                errors.append(f"{item['id']} 引用了未知任务")
            if status in {"planned", "ported"} and item.get("runtime_verified_in_new_project") is not False:
                errors.append(f"{item['id']} 未完成工具不能宣称运行验证通过")
            if status == "verified":
                for field in ["implementation_files", "verification_evidence"]:
                    paths = item.get(field)
                    if not isinstance(paths,list) or not paths or any(not _inside(root,p).is_file() for p in paths):
                        errors.append(f"{item['id']} 验证状态缺少实际 {field}")
                if item.get("runtime_verified_in_new_project") is not True:
                    errors.append(f"{item['id']} 验证状态缺少运行验证标志")
                for proof_path in item.get("verification_evidence", []):
                    evidence = load_json(_inside(root,proof_path))
                    if evidence.get("success") is not True or item['id'] not in evidence.get("verified_tool_ids",[]):
                        errors.append(f"{item['id']} 验证证据没有对应的成功检查")
                    manifest = evidence.get("content_sha256",{})
                    for impl in item.get("implementation_files",[]) + item.get("verification_tests",[]):
                        actual = hashlib.sha256(_inside(root,impl).read_bytes()).hexdigest()
                        if manifest.get(impl) != actual:
                            errors.append(f"{item['id']} 实现已变化，需重新验证: {impl}")

        if project.get("cad_tools_available") is not False and not any(t.get("implementation_status") == "verified" for t in tools.values()):
            errors.append("没有已验证几何工具，却声明 CAD 能力可用")
        checks.extend(["catalog_ids_and_source_references", "planned_vs_verified_capabilities"])
        if check_sources:
            checks.append("read_only_source_sha256_comparison")
    except (CatalogError, OSError, KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return {"success":not errors,"project_root":str(root),"counts":counts,"checks":checks,"sources_checked":check_sources,"source_results":source_results,"errors":errors,"cad_generation_executed":False}
