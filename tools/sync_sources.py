"""从现有三个独立目录同步源码副本到本仓库；不移动、不删除原项目。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

PROJECTS = {
    'Crawl4AI': ('listing_ingest', 'config', 'docs', 'tests'),
    'ListingStage2': ('src', 'config', 'docs', 'tests'),
    'ListingStage3': ('src', 'config', 'docs', 'tests', 'web'),
}
EXTENSIONS = {'.py', '.ps1', '.json', '.jsonc', '.md', '.toml', '.lock', '.txt', '.sql', '.html', '.js', '.css', '.drawio', '.xml'}
SECRET = re.compile(r'(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path('D:/'))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    copies = []
    # 先完成全部扫描，再复制。拒绝符号链接及常见密钥格式；不要在输出中打印密钥内容。
    for name, directories in PROJECTS.items():
        source = (args.source_root / name).resolve()
        if source == (repo / name).resolve() or not source.is_dir():
            raise ValueError(f'无效来源目录：{source}')
        paths = list(source.iterdir())
        for directory in directories:
            paths.extend((source / directory).rglob('*'))
        for path in paths:
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(source)
            if any(part.startswith('.') or part in {'__pycache__', 'node_modules', 'data', 'outputs', 'library'} for part in relative.parts):
                continue
            if '.local.' in path.name or path.suffix.lower() not in EXTENSIONS:
                continue
            if path.name in {'cleanup-report.json', 'project-manifest.json'}:
                continue
            if path.stat().st_size > 5 * 1024 * 1024:
                raise ValueError(f'文件过大，需要单独审查：{path}')
            raw = path.read_bytes()
            text = raw.decode('utf-8-sig')
            if SECRET.search(text):
                raise ValueError(f'疑似凭据，请本地核对：{path}')
            if path.suffix == '.json':
                # 配置中的 API key/password 必须为空或从环境读取；不自动上传非空口令字段。
                def check(value):
                    if isinstance(value, dict):
                        for key, item in value.items():
                            if key.lower() in {'password', 'api_key', 'secret_key', 'access_token', 'client_secret'} and item:
                                raise ValueError(f'发现非空凭据字段：{path}')
                            check(item)
                    elif isinstance(value, list):
                        for item in value:
                            check(item)
                check(json.loads(text))
            copies.append((path, repo / name / relative, hashlib.sha256(raw).hexdigest()))
    for path, target, sha in copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    manifest = {str(target.relative_to(repo)).replace('\\', '/'): sha for _, target, sha in copies}
    (repo / 'source-files.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Synced {len(copies)} source/document/config files; media, vectors, credentials and runtime outputs excluded.')
    print('同步不删除仓库内旧文件；若原项目删除文件，请核对 git diff 后手动同步删除。')


if __name__ == '__main__':
    main()
