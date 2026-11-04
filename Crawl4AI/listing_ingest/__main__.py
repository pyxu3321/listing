# 文件用途：单来源CLI入口：读取topper-us.json，允许覆盖商品数量或显式测试链接，调用runner.run。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
import argparse
import asyncio
import json
from pathlib import Path

from .runner import PROJECT, load_config, run


# 功能及输出：读取单来源CLI，调用异步采集；输出报告位置并返回0/2状态码。
def main() -> int:
    parser = argparse.ArgumentParser(description="Topper BSR + listing media live collection pilot")
    parser.add_argument("--config", type=Path, default=PROJECT / "config" / "topper-us.json")
    parser.add_argument("--library", type=Path, help="Local archive root; defaults to project library/")
    parser.add_argument("--max-products", type=int, help="Override detail-page test limit, 0-50")
    parser.add_argument("--product-url", action="append", default=[], help="Explicit extra product test URL; never inferred as a ranking")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.max_products is not None:
        if not 0 <= args.max_products <= 50:
            parser.error("--max-products must be 0-50")
        config["max_products"] = args.max_products
    report, directory = asyncio.run(run(config, library_override=args.library, product_urls=args.product_url))
    print(json.dumps({"status": report["status"], **report["summary"], "report": str(directory / "index.html"), "json": str(directory / "report.json")}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
