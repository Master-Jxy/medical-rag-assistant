# Stage 24 开源对标与许可记录

> 调研日期：2026-08-06。Star 数会变化，仅作为本次选型证据。本文记录借鉴思想，不表示复制源码。

## 1. 对标结果

| 项目 | 调研时 Star | 许可 | 具体参考路径 | 借鉴内容 |
| --- | ---: | --- | --- | --- |
| [Docling](https://github.com/docling-project/docling) | 64,287 | MIT | `docs/examples/custom_convert.py`、`docling/document_converter.py`、`docling_core/types/doc/document.py`、`docling_core/types/doc/base.py`、`docling/cli/main.py` | 统一 DocumentConverter、Document/Provenance/Table 结构化产物、表格导出后再由应用层归一化 |
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

## 2.1 Stage 24.3 具体采用记录

- Docling：参考 `DocumentConverter` 统一转换入口、Document 元素、provenance/page 定位和
  Table 导出思想；本项目只在 `infrastructure` 内做可选惰性 adapter，把结果转换为自有
  `ParsedDocument` 契约，没有复制 Docling 源码，也没有把 Docling 对象传入业务服务。
- RAGFlow：参考 parser 失败可见、任务状态和 fallback 可观测思想；本项目仍复用现有
  `parser_experiments` 与审核发布 lifecycle，没有复制 RAGFlow 任务执行器或引入分布式队列。
- 依赖：本阶段未新增 required dependency，未安装 Docling；Docling 仍是重型可选候选，
  生产默认关闭。若后续真实评估需要安装，必须另行记录精确版本、MIT 许可、镜像体积、
  内存占用和 2 核 2G 部署影响。

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
## 5. Stage 24.4 adopted references

- Docling (MIT): referenced `docling_core/types/doc/document.py` and
  `docling_core/types/doc/base.py` for the idea of page/picture provenance.
  The project keeps only its own `ParsedAsset` contract and does not copy
  Docling code or pass Docling objects into application services.
- Unstructured (Apache-2.0): referenced `unstructured/partition/pdf.py` and
  `unstructured/partition/image.py` for the boundary between file partition,
  hi-res/OCR strategy selection, and normalized elements. No Unstructured code
  or dependency was copied or installed.
- Dify (modified Apache-2.0 with additional terms): referenced
  `api/services/dataset_service.py` and
  `api/tests/unit_tests/services/test_dataset_service_document.py` for file/image
  upload quotas and dataset document status thinking. No restricted source,
  UI, or product behavior was copied.
- RAGFlow (Apache-2.0): referenced `rag/svr/task_executor.py`,
  `api/apps/services/document_api_service.py`, and
  `web/src/interfaces/database/document.ts` for parser task status and
  administrator-visible failure state ideas. No task executor implementation or
  distributed queue was copied.

Stage 24.4 added `Pillow==12.3.0` (HPND license) only for lightweight local
PNG/JPEG structure and dimension validation. It did not introduce Docling,
MinerU, Unstructured, OCR engines, vision SDKs, or online model downloads.
