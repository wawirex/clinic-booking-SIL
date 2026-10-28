class DomainError(Exception):
    """Business-rule failure that maps cleanly onto an HTTP response."""

    status_code = 400

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class NotFoundError(DomainError):
    status_code = 404


class UnprocessableError(DomainError):
    """The request is well-formed but violates a booking rule (hours, past, alignment)."""

    status_code = 422


class ConflictError(DomainError):
    """The request conflicts with current state (slot taken, already cancelled)."""

    status_code = 409
