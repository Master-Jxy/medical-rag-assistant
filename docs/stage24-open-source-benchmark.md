# Stage 24 开源对标与许可记录

> 调研日期：2026-08-06。Star 数会变化，仅作为本次选型证据。本文记录借鉴思想，不表示复制源码。

## 1. 对标结果

| 项目 | 调研时 Star | 许可 | 具体参考路径 | 借鉴内容 |
| --- | ---: | --- | --- | --- |
| [Docling](https://github.com/docling-project/docling) | 64,287 | MIT | `docs/examples/custom_convert.py`、`docs/examples/full_page_ocr.py`、`docling/cli/main.py` | 统一 DocumentConverter、按选项启用 OCR/表格、结构化文档后再导出 |
| [MinerU](https://github.com/opendatalab/MinerU) | 76,868 | Apache-2.0 + 额外商业条款 | `README.md`、`README_zh-CN.md` 及其 PDF/OCR pipeline 说明 | 文本型/扫描型 PDF 路由、版面/表格/图片中间产物；只借鉴流程，不复制代码 |
| [RAGFlow](https://github.com/infiniflow/ragflow) | 86,897 | Apache-2.0 | `rag/svr/task_executor.py`、`api/apps/services/document_api_service.py`、`web/src/interfaces/database/document.ts` | 文档处理任务状态、解析器选择、失败可见、解析和索引解耦 |
| [Unstructured](https://github.com/Unstructured-IO/unstructured) | 15,261 | Apache-2.0 | `unstructured/partition/auto.py`、`partition/pdf.py`、`partition/image.py` | 文件类型分派、统一 Element 模型、PDF 策略选择与测试矩阵 |
| [Dify](https://github.com/langgenius/dify) | 151,446 | 修改版 Apache-2.0，含额外条件 | `api/services/dataset_service.py`、`api/tests/unit_tests/services/test_dataset_service_document.py` | 数据集文档状态、处理规则、管理端治理和失败状态；不复制受附加条款约束的实现 |
| [Haystack](https://github.com/deepset-ai/haystack) | 26,117 | Apache-2.0 | `haystack/components/converters/pypdf.py`、`preprocessors/document_splitter.py`、`markdown_header_splitter.py`、`extractors/llm_metadata_extractor.py` | Converter/Cleaner/Splitter 可组合契约、Markdown 标题切分、元数据提取独立组件 |

上述仓库在 2026-08-05/06 均有近期活动。GitHub API 对 MinerU 和 Dify 返回的 SPDX 许可
不能表达其额外条款，因此本项目按仓库 LICENSE 原文处理，不把它们视为纯 Apache-2.0。

## 2. 采用的共同思想

1. 先转换成统一结构化元素，再清洗、切片、索引。
2. 文件类型、解析策略和外部供应商由注册表/Port 选择，业务层不依赖第三方对象。
3. 解析与索引是两个状态阶段，解析失败可见、可重试、不能静默发布。
4. OCR、表格和视觉是能力开关，有固定评估集和回退基线。
5. 元数据提取是独立步骤，AI 建议与正式元数据分离。
6. 管理员可以看到处理状态、警告、来源和版本，而不是只看到“上传成功”。

## 3. 明确不照搬

- 不复制 Dify/MinerU 的源码、商标、页面或许可证受限部分。
- 不复制 RAGFlow 的大规模任务基础设施；当前项目仍用模块化单体和现有 JobPort。
- 不一次安装 Docling、MinerU、Unstructured 三套重型解析栈。先用契约和固定集比较，
  最多晋级一个生产 PDF 解析器。
- 不照搬多租户、插件市场、分布式队列、Kubernetes 或完整数据集平台。
- 不把开源项目的医疗示例当成经过临床审核的数据。

## 4. 代码与许可执行规则

- 新代码优先由本项目按契约独立实现；确需引用 MIT/Apache-2.0 片段时保留版权和 NOTICE，
  并在提交中记录来源、文件、版本和修改。
- 含附加商业条款、AGPL 或来源不清的实现只做黑盒/架构参考。
- 新依赖必须记录版本、许可证、镜像体积、内存需求和是否适合 2 核 2G 服务器。
- 每个 Stage 24 子任务在交接中写明“参考了哪个项目的哪个路径、采用了什么、没有复制什么”。
