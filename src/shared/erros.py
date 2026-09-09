class DomainError(Exception):
    status = 500


class Unauthorized(DomainError):
    status = 401


class MissingRequirement(DomainError):
    status = 400


class Forbidden(DomainError):
    status = 403


class NotFound(DomainError):
    status = 404


class AlreadyExists(DomainError):
    status = 409


class Invalid(DomainError):
    status = 422
