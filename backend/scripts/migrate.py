from alembic import command
from alembic.config import Config


if __name__ == "__main__":
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    print("business migration complete: head")
