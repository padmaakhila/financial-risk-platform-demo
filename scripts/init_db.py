"""Create all tables and default settings. Safe to run repeatedly.
Run from the project root: python -m scripts.init_db
"""

from backend.core.constants import DEFAULT_SETTINGS
from backend.database.session import get_engine, session_scope
from backend.models import Base, Setting


def init_db() -> None:
    engine = get_engine()

    Base.metadata.create_all(engine)

    with session_scope() as s:
        for key, (value, desc) in DEFAULT_SETTINGS.items():
            if s.get(Setting, key) is None:
                s.add(Setting(key=key, value=value, description=desc))


if __name__ == "__main__":
    init_db()
    print(
        "Database ready:",
        get_engine().url.render_as_string(hide_password=True),
    )