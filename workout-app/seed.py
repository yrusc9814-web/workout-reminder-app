from database import init_db


def seed_database():
    """Initialize and seed the database using database.py's idempotent logic."""
    return init_db()


if __name__ == "__main__":
    seed_database()
    print("Database initialized and seeded successfully.")
