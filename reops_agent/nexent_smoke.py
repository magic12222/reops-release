"""旧 smoke 入口兼容层，默认离线，统一使用 Phase 7A Gate。"""
from .model_smoke import main

if __name__ == "__main__":
    raise SystemExit(main())
