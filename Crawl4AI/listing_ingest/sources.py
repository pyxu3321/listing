# 文件用途：多来源注册表入口：合并默认与来源配置，校验计划，按来源顺序执行；--plan不联网。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
"""Validated multi-source plans; execute sequentially using the existing crawler."""
from __future__ import annotations
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from .runner import PROJECT, load_config, validate_config, run


# Engine defaults keep the user-facing source list short. Existing collection
# budgets are preserved; each source can override them explicitly.
DEFAULTS = {
    "source_type": "amazon_bestsellers", "max_products": 50, "rank_end": 50,
    "max_images_per_product": 4, "max_videos_per_product": 0,
    "max_description_images_per_product": 20, "max_aplus_images_per_product": 40,
    "media_concurrency": 3, "ocr_enabled": True, "request_delay_seconds": 3,
    "page_timeout_ms": 60000, "max_image_bytes": 20971520,
    "max_video_bytes": 104857600, "storage_backend": "local",
    "library_directory": "library", "delivery_location": None,
}


# 功能及输出：输入注册表及可选来源选择；合并引擎默认→全局默认→单来源，处理旧config引用，返回经校验任务列表。
# 参数：registry（多来源清单对象）；selected（选中的来源ID列表）；base_dir（旧配置相对路径基准）。
def normalize_sources(registry: dict, selected: list[str] | None = None,
                      base_dir: Path | None = None) -> list[dict]:
    """Common boundary: future Excel/SQL readers supply this same document shape.

    Only the compatibility `config` field performs file I/O; inline rows do not.
    Merge is shallow: engine defaults < document defaults < source values.
    """
    from copy import deepcopy
    if not isinstance(registry, dict) or registry.get("schema_version", 1) != 1 or not isinstance(registry.get("sources"), list):
        raise ValueError("Expected schema_version=1 and sources array")
    defaults = registry.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("defaults must be an object")
    if set(defaults) & {"id", "source_id", "url", "ranking_url", "config", "enabled"}:
        raise ValueError("Source identity, URL and enabled belong in each source, not defaults")
    seen, tasks = set(), []
    for entry in registry["sources"]:
        if not isinstance(entry, dict):
            raise ValueError("Each source must be an object")
        source_id = entry.get("id", entry.get("source_id"))
        if "id" in entry and "source_id" in entry and entry["id"] != entry["source_id"]:
            raise ValueError("Conflicting id and source_id")
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            raise ValueError("Missing or duplicate source id")
        seen.add(source_id)
        if not isinstance(entry.get("enabled", True), bool):
            raise ValueError("enabled must be boolean")
        if selected and source_id not in selected:
            continue
        if not entry.get("enabled", True):
            if selected:
                raise ValueError(f"Source is disabled: {source_id}")
            continue
        values = deepcopy(entry)
        config_path = None
        if "config" in values:
            if "url" in values or "ranking_url" in values:
                raise ValueError("Do not mix legacy config reference and inline URL")
            if base_dir is None:
                raise ValueError("Legacy config reference requires base_dir")
            config_path = (base_dir / values.pop("config")).resolve()
            legacy = load_config(config_path)
            if legacy["source_id"] != source_id:
                raise ValueError("Registry and config source_id mismatch")
            values = {**legacy, **values}
        if "url" in values and "ranking_url" in values and values["url"] != values["ranking_url"]:
            raise ValueError("Conflicting url and ranking_url")
        if "url" in values:
            values["ranking_url"] = values.pop("url")
        values.pop("id", None)
        values.pop("enabled", None)
        # 配置浅层覆盖顺序：引擎默认 < 注册表defaults < 单来源，随后统一校验适配范围。
        config = validate_config({**DEFAULTS, **deepcopy(defaults), **values, "source_id": source_id})
        tasks.append({"source_id": source_id, "config_path": str(config_path) if config_path else None, "config": config})
    if selected and set(selected) - seen:
        raise ValueError("Unknown selected source id")
    if not tasks:
        raise ValueError("No enabled sources selected")
    return tasks


# 功能及输出：读取sources.json，返回规范任务；不启动采集或联网。
# 参数：path（本地文件路径）；selected（选中的来源ID列表）。
def plan(path: Path, selected: list[str] | None = None) -> list[dict]:
    registry = json.loads(path.read_text(encoding="utf-8-sig"))
    return normalize_sources(registry, selected, path.parent)


# 功能及输出：按来源顺序调用既有采集器；单来源失败仍继续其余来源，返回批次结果。
# 参数：tasks（规范采集任务列表）；library（可选归档目录）。
async def execute(tasks: list[dict], library: Path | None = None) -> dict:
    results = []
    for task in tasks:
        try:
            report, directory = await run(task["config"], library_override=library)
            results.append({"source_id": task["source_id"], "status": report["status"], "report": str(directory / "report.json")})
        except Exception as exc:
            results.append({"source_id": task["source_id"], "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return {"schema_version": 1, "finished_at": datetime.now(timezone.utc).isoformat(), "status": "success" if all(x["status"] == "success" for x in results) else "partial_failed", "sources": results}


# 功能及输出：多来源CLI；--plan仅打印计划，否则执行来源并写批次清单，返回0/2退出码。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=PROJECT / "config/sources.json")
    parser.add_argument("--source", action="append", help="Select source_id; repeat for multiple sources")
    parser.add_argument("--library", type=Path)
    parser.add_argument("--plan", action="store_true", help="Validate and print plan without network calls")
    args = parser.parse_args()
    tasks = plan(args.sources.resolve(), args.source)
    # 此分支只返回已校验计划，不执行下面的浏览器采集。
    if args.plan:
        print(json.dumps(tasks, ensure_ascii=False, indent=2))
        return 0
    result = asyncio.run(execute(tasks, args.library))
    target = (args.library or PROJECT / "library") / "source_batches"
    target.mkdir(parents=True, exist_ok=True)
    import uuid
    output = target / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8] + ".json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**result, "batch_manifest": str(output)}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
