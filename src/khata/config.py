import os


class Config:
    def __init__(self):
        self.secret_key = os.environ.get("KHATA_SECRET_KEY", "dev-only-change-me")
        self.database_url = os.environ.get("KHATA_DATABASE_URL", "sqlite:///khata.db")
        self.env = os.environ.get("KHATA_ENV", "development")
        self.google_client_id = os.environ.get("KHATA_GOOGLE_CLIENT_ID")
        self.price_feed = os.environ.get("KHATA_PRICE_FEED")
        self.testing = False
