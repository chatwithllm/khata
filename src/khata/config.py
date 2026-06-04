import os


class Config:
    def __init__(self):
        self.secret_key = os.environ.get("KHATA_SECRET_KEY", "dev-only-change-me")
        self.database_url = os.environ.get("KHATA_DATABASE_URL", "sqlite:///khata.db")
        self.env = os.environ.get("KHATA_ENV", "development")
        self.testing = False
