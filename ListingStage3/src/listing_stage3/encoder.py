"""复用第二阶段本地编码配方，避免生成不兼容的查询向量。"""
import sys
from pathlib import Path


def create(settings):
    """按配置加载第二阶段编码器；需要本地Ollama，不调用付费API。"""
    source=Path(settings['stage2_project'])/'src'
    if not source.is_dir():raise ValueError('Stage-two project path does not exist')
    sys.path.insert(0,str(source))
    from listing_stage2.local_encoder import LocalEncoder
    return LocalEncoder(Path(settings['cache_directory']),url=settings['ollama_url'],model=settings['model'])
