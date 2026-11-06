"""Error types shared by the services.

* ``PermanentError`` - retrying will not help (private video, too large, ...).
* ``TransientError`` - temporary problem (network, rate limit); retry later.
* ``NotReadyError``   - video exists but cannot be processed yet
  (upcoming premiere / live stream in progress).
"""


class AurixError(Exception):
    """Base error. ``user_message`` is safe to show to Telegram users."""

    user_message = "Xatolik yuz berdi. Keyinroq qayta urinib ko'ring."

    def __init__(self, message: str = "", user_message: str | None = None) -> None:
        super().__init__(message or self.user_message)
        if user_message:
            self.user_message = user_message


class PermanentError(AurixError):
    user_message = "Bu videoni yuklab bo'lmaydi."


class TransientError(AurixError):
    user_message = "Vaqtinchalik xatolik. Birozdan so'ng qayta urinib ko'ring."


class NotReadyError(TransientError):
    user_message = "Video hali tayyor emas (premyera yoki jonli efir)."


class FileTooLargeError(PermanentError):
    user_message = "Fayl Telegram limitidan katta, yuborib bo'lmaydi."


class DestinationError(TransientError):
    """The Telegram destination channel is missing or the bot lacks rights.

    This is an operator configuration problem, not a problem of the video,
    so the job waits (without using up retry attempts) until it is fixed.
    """

    user_message = "Telegram kanal sozlanmagan yoki bot kanalga admin emas."
