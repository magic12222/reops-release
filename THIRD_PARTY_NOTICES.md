# 第三方组件与版权

本交付为源码包，不包含 Python/Node 依赖二进制、Docker 镜像、数据库或运行历史。
安装时从各组件发行渠道获取依赖，相关许可仍适用。

| 组件 | 用途 | 许可及来源 |
| --- | --- | --- |
| Vikunja 2.7.1 | 独立受监控任务应用，未修改上游程序 | AGPL-3.0；原文见 `integrations/vikunja/LICENSE.upstream`；[对应源码](https://github.com/go-vikunja/vikunja/tree/v2.7.1) |
| PostgreSQL 16 | 独立应用数据库，用户自行下载镜像 | [PostgreSQL License](https://www.postgresql.org/about/licence/)；[Docker 镜像构建源码](https://github.com/docker-library/postgres) |
| Nexent SDK | 可选 OpenAI 兼容模型适配 | 固定提交 `1d089e1ca47bea838860c141845b6cd4e6f205c2`，MIT；原文见 `licenses/nexent-MIT.txt`；[源码](https://github.com/ModelEngine-Group/nexent/tree/1d089e1ca47bea838860c141845b6cd4e6f205c2) |
| React / React DOM | 网页组件 | MIT，见 `licenses/react-*.txt` 和 `licenses/react-dom-*.txt` |
| Motion | 网页动画 | MIT，见 `licenses/motion-*.txt` |
| Lucide React | 图标 | ISC，见 `licenses/lucide-react-*.txt` |
| Geist Sans / Geist Mono | 网页字体 | SIL OFL 1.1，见 `licenses/fontsource-*.txt`，保留 Vercel / basement.studio 署名 |

FastAPI、Uvicorn、HTTPX、Psycopg、Redis 客户端、JSON Schema、测试与构建工具等通过依赖安装；
版本分别由 `requirements-lock.txt`、`requirements-nexent.txt`、`web/pnpm-lock.yaml` 指定。
这些独立组件不改用 ReOps 原创部分的版权声明。

ResearchLoop-AI 外部副本未取得本次公开分发确认，故不包含其源码、构建文件或运行数据。
本版运行入口为 Vikunja；保留的 ReOps 兼容适配代码不提供 ResearchLoop 实验环境。
ReOps Logo 为本项目提供的品牌资源，不代表第三方对本项目背书。
