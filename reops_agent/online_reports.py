"""在线报告的单文件完整替换；JSON 是权威证据，不提供跨文件事务。"""

import os
from pathlib import Path
import tempfile


class ReportPersistenceError(RuntimeError):
    """只暴露固定分类；保存失败不代表执行未发生或已回滚。"""

    def __init__(self, artifact, stage, *, json_committed=False):
        self.artifact = artifact
        self.stage = stage
        self.json_committed = json_committed
        super().__init__(f"online_report_{artifact}_{stage}_failed")


def replace_complete(path, text, *, artifact, json_committed=False):
    """同步临时文件后替换，失败保留旧目标；不保证目录断电持久性。"""
    path = Path(path)
    temporary = None
    stage = "write"
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            stage = "fsync"
            os.fsync(stream.fileno())
        stage = "replace"
        os.replace(temporary, path)
    except Exception:
        raise ReportPersistenceError(artifact, stage, json_committed=json_committed) from None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                # 替换成功时临时文件已不存在；清理不能掩盖主要结果。
                pass


def save_pair(value, directory, json_name, markdown_name):
    """摘要来自已嵌入 JSON 的同份内容；摘要失败仍可从 JSON 重建。"""
    import json
    try:
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    except Exception:
        raise ReportPersistenceError("json", "serialize") from None
    replace_complete(directory / json_name, payload, artifact="json")
    replace_complete(directory / markdown_name, value["summary_markdown"],
                     artifact="markdown", json_committed=True)
    return value
