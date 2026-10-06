"""Dashboard login helpers."""

from app.core.auth import check_login, parse_users
from app.db.session import normalize_db_url


def test_parse_users_handles_several_users_and_colons_in_passwords():
    users = parse_users(" user1:Example@1234 , mom:a:b:c ,broken, :nopass, dad: ")
    assert users == {"user1": "Example@1234", "mom": "a:b:c"}


def test_check_login():
    users = parse_users("user1:Example@1234")
    assert check_login("user1", "Example@1234", users)
    assert check_login(" user1 ", "Example@1234", users)  # stray spaces in the ID are fine
    assert not check_login("user1", "surya@1111", users)  # passwords are case-sensitive
    assert not check_login("someone", "Example@1234", users)
    assert not check_login("", "", {})


def test_postgres_urls_use_psycopg_driver():
    assert normalize_db_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("postgresql://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert normalize_db_url("sqlite:///x.db") == "sqlite:///x.db"
