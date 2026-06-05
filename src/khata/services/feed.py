class FeedError(Exception):
    pass


def feed_enabled(cfg) -> bool:
    return bool(getattr(cfg, "price_feed", None))


def live_price_provider(asset_class, symbol, currency, feed_config):
    """Default provider — NOT wired out of the box. A self-hoster sets KHATA_PRICE_FEED and either
    overrides app.config['PRICE_PROVIDER'] or implements a fetch here (lazily importing `requests`)
    against their market-data source, returning an integer price in minor units per whole unit.
    Until then, feeds raise and the app stays on manual quotes."""
    raise FeedError("no price provider configured")
