from fastapi import HTTPException, status


class AuthError(HTTPException):
    """Generic authentication failure (invalid token, SSO failure, …)."""

    def __init__(self, detail: str = "Authentication error"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class NotInvited(HTTPException):
    """The email is not in any pending invitation and is not the bootstrap admin."""

    def __init__(self, email: str | None = None):
        detail = f"Email {email} is not invited" if email else "Email is not invited"
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class InvalidToken(HTTPException):
    """The JWT is malformed, expired, or has the wrong type claim."""

    def __init__(self, detail: str = "Invalid or expired token"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class NotAdmin(HTTPException):
    """The authenticated user does not have the admin role."""

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )


class InvalidCredentials(HTTPException):
    """Email or password is incorrect, or the user has no password set."""

    def __init__(self, detail: str = "Invalid email or password"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


class InvitationNotFound(HTTPException):
    """The invitation does not exist."""

    def __init__(self, invitation_id: int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invitation with id {invitation_id} not found",
        )


class InvitationAlreadyExists(HTTPException):
    """An invitation for this email already exists."""

    def __init__(self, email: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An invitation for {email} already exists",
        )
