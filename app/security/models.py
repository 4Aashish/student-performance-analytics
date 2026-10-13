from dataclasses import dataclass
from typing import Optional

ROLES = ("admin", "teacher", "student")


class AuthorizationError(Exception):
    """The logged-in user is not allowed to do this."""


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str
    role: str
    teacher_id: Optional[int] = None
    student_id: Optional[int] = None
