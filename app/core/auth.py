"""Dashboard login.

Users come from the DASHBOARD_USERS setting (in .env locally, or in Render's
environment settings), never from the code, because the repo is public:

    DASHBOARD_USERS=myid:MyPassword,mom:AnotherPassword

Format: id:password pairs separated by commas (so passwords can't contain commas).
"""

import hmac


def parse_users(raw: str) -> dict[str, str]:
    users: dict[str, str] = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if ":" in entry:
            user_id, password = entry.split(":", 1)  # split on the FIRST ":" only
            if user_id.strip() and password:
                users[user_id.strip()] = password
    return users


def check_login(user_id: str, password: str, users: dict[str, str]) -> bool:
    expected = users.get((user_id or "").strip())
    if expected is None:
        return False
    # compare_digest takes the same time whether the password is close or not (no timing hints)
    return hmac.compare_digest(password.encode(), expected.encode())
