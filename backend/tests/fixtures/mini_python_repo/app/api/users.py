"""User endpoints."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/users")


class UserService:
    """In-memory user store."""

    def __init__(self) -> None:
        self.users: dict[int, str] = {}

    def create(self, name: str) -> int:
        user_id = len(self.users) + 1
        self.users[user_id] = name
        return user_id

    def get(self, user_id: int) -> str:
        if user_id not in self.users:
            raise KeyError(user_id)
        return self.users[user_id]


service = UserService()


@router.get("/{user_id}")
def read_user(user_id: int) -> dict[str, str]:
    """Return one user."""
    try:
        return {"name": service.get(user_id)}
    except KeyError:
        raise HTTPException(status_code=404) from None


@router.post("/")
def create_user(name: str) -> dict[str, int]:
    """Create a user."""
    return {"id": service.create(name)}


class ReportBuilder:
    """Deliberately long class (> 120 lines)."""

    def report_1(self) -> int:
        """Build report number 1."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_2(self) -> int:
        """Build report number 2."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_3(self) -> int:
        """Build report number 3."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_4(self) -> int:
        """Build report number 4."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_5(self) -> int:
        """Build report number 5."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_6(self) -> int:
        """Build report number 6."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_7(self) -> int:
        """Build report number 7."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_8(self) -> int:
        """Build report number 8."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_9(self) -> int:
        """Build report number 9."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_10(self) -> int:
        """Build report number 10."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_11(self) -> int:
        """Build report number 11."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total

    def report_12(self) -> int:
        """Build report number 12."""
        total = 0
        total += 1  # step 1
        total += 2  # step 2
        total += 3  # step 3
        total += 4  # step 4
        total += 5  # step 5
        total += 6  # step 6
        total += 7  # step 7
        total += 8  # step 8
        total += 9  # step 9
        total += 10  # step 10
        return total
