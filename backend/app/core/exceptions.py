"""业务异常及其统一 HTTP 响应。"""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.ports.telemetry import NullTelemetry, TelemetryEvent, emit_safely


class AppError(Exception):
    """可安全展示给前端的业务异常。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.headers = headers or {}


class ConfigurationError(AppError):
    def __init__(self, message: str = "模型服务尚未配置") -> None:
        super().__init__(message, code="CONFIGURATION_ERROR", status_code=503)


class RagServiceError(AppError):
    def __init__(self, message: str = "问答服务暂时不可用，请稍后重试") -> None:
        super().__init__(message, code="RAG_SERVICE_ERROR", status_code=503)


class AgentDisabledError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "资料Agent当前未启用",
            code="AGENT_DISABLED",
            status_code=503,
        )


class AgentRunNotFoundAppError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "未找到指定Agent运行",
            code="AGENT_RUN_NOT_FOUND",
            status_code=404,
        )


class AgentRunConflictError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "当前Agent运行状态不允许该操作",
            code="AGENT_RUN_CONFLICT",
            status_code=409,
        )


class AgentThreadNotFoundAppError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "未找到指定Agent会话",
            code="AGENT_THREAD_NOT_FOUND",
            status_code=404,
        )


class AgentMessageNotFoundAppError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "未找到指定Agent消息",
            code="AGENT_MESSAGE_NOT_FOUND",
            status_code=404,
        )


class AgentMessageConflictError(AppError):
    def __init__(self, message: str = "当前Agent消息状态不允许该操作") -> None:
        super().__init__(
            message,
            code="AGENT_MESSAGE_CONFLICT",
            status_code=409,
        )


class UnsupportedFileTypeError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "仅支持 PDF、TXT、DOCX、Markdown 和 HTML 文件",
            code="UNSUPPORTED_FILE_TYPE",
            status_code=400,
        )


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


class DocumentDeleteForbiddenError(AppError):
    def __init__(self) -> None:
        super().__init__("无权删除该文档", code="DOCUMENT_DELETE_FORBIDDEN", status_code=403)


class SystemDocumentRequiredError(AppError):
    def __init__(self) -> None:
        super().__init__("该操作仅适用于系统文档", code="SYSTEM_DOCUMENT_REQUIRED", status_code=409)


class DocumentBusyError(AppError):
    def __init__(self) -> None:
        super().__init__("文档正在被其他操作处理，请稍后重试", code="DOCUMENT_BUSY", status_code=409)


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
        persistence_codes = {"CONVERSATION_STORE_ERROR", "DOCUMENT_STORE_ERROR"}
        emit_safely(
            getattr(request.app.state, "telemetry", NullTelemetry()),
            TelemetryEvent.create(
                request_id=request_id,
                event_name=(
                    "persistence_failure"
                    if exc.code in persistence_codes
                    else "application_error"
                ),
                result="failure",
                route=request.url.path,
                user_id=getattr(request.state, "user_id", None),
                status_code=exc.status_code,
                error_type=exc.code,
            ),
        )
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "error": {"code": exc.code, "message": exc.message},
                "request_id": request_id,
            },
        )
