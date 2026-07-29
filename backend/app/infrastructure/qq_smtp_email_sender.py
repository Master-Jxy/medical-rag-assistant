"""QQ SMTP邮件发送适配器；不记录凭据、收件地址或验证码。"""

import smtplib
from email.message import EmailMessage
from typing import Callable

from app.core.config import Settings
from app.modules.auth.ports import VerificationPurpose


class QQSmtpEmailSender:
    def __init__(
        self,
        settings: Settings,
        smtp_ssl_factory: Callable[..., object] = smtplib.SMTP_SSL,
    ) -> None:
        self.settings = settings
        self.smtp_ssl_factory = smtp_ssl_factory

    def send_verification_code(
        self,
        *,
        recipient: str,
        purpose: VerificationPurpose,
        code: str,
        ttl_seconds: int,
    ) -> None:
        if not self.settings.smtp_use_ssl:
            raise ValueError("QQ SMTP当前仅支持SSL")
        username, password = self.settings.require_smtp_credentials()
        message = EmailMessage()
        message["From"] = f"{self.settings.mail_from_name} <{username}>"
        message["To"] = recipient
        message["Subject"] = (
            "注册验证码"
            if purpose is VerificationPurpose.REGISTER
            else "密码重置验证码"
        )
        minutes = max(1, ttl_seconds // 60)
        message.set_content(
            f"您的验证码是：{code}\n验证码将在{minutes}分钟后失效。"
            "\n如果不是您本人操作，请忽略此邮件。"
        )
        with self.smtp_ssl_factory(
            self.settings.smtp_host,
            self.settings.smtp_port,
            timeout=self.settings.smtp_timeout_seconds,
        ) as client:
            client.login(username, password)  # type: ignore[attr-defined]
            client.send_message(message)  # type: ignore[attr-defined]
