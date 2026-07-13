"""业务异常及其统一 HTTP 响应。"""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """可安全展示给前端的业务异常。"""

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class ConfigurationError(AppError):
    def __init__(self, message: str = "模型服务尚未配置") -> None:
        super().__init__(message, code="CONFIGURATION_ERROR", status_code=503)


class RagServiceError(AppError):
    def __init__(self, message: str = "问答服务暂时不可用，请稍后重试") -> None:
        super().__init__(message, code="RAG_SERVICE_ERROR", status_code=503)


class UnsupportedFileTypeError(AppError):
    def __init__(self) -> None:
        super().__init__("仅支持 PDF 和 TXT 文件", code="UNSUPPORTED_FILE_TYPE", status_code=400)


class FileTooLargeError(AppError):
    def __init__(self, max_size_mb: int) -> None:
        super().__init__(
            f"文件大小不能超过 {max_size_mb} MB",
            code="FILE_TOO_LARGE",
            status_code=413,
        )


class DuplicateDocumentError(AppError):
    def __init__(self) -> None:
        super().__init__("该文件已经上传过，请勿重复入库", code="DUPLICATE_DOCUMENT", status_code=409)


class DocumentParseError(AppError):
    def __init__(self, message: str = "文档解析失败或没有有效文本") -> None:
        super().__init__(message, code="DOCUMENT_PARSE_ERROR", status_code=422)


class DocumentStoreError(AppError):
    def __init__(self) -> None:
        super().__init__("文档入库失败，请稍后重试", code="DOCUMENT_STORE_ERROR", status_code=500)


class DocumentNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("未找到指定文档", code="DOCUMENT_NOT_FOUND", status_code=404)


class ConversationNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("未找到指定会话", code="CONVERSATION_NOT_FOUND", status_code=404)


class ConversationStoreError(AppError):
    def __init__(self) -> None:
        super().__init__("会话服务暂时不可用，请稍后重试", code="CONVERSATION_STORE_ERROR", status_code=500)


def register_exception_handlers(app: FastAPI) -> None:
    """把业务异常统一转换成稳定的 JSON，避免向前端暴露 Traceback。"""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": exc.code, "message": exc.message},
                "request_id": request_id,
            },
        )
