"""Real (non-mock) ingestion adapters.

Each provider normalizes to RawSnapshot / domain DTOs. Aggregation across providers
happens in ``aggregate.py`` before the pipeline sees an IngestBundle.
"""

from .aggregate import aggregate_snapshots
from .coingecko import CoinGeckoClient, CoinGeckoGlobalSource, CoinGeckoPriceSource
from .coinmarketcap import (
    CoinMarketCapClient,
    CoinMarketCapGlobalSource,
    CoinMarketCapSnapshots,
)
from .gate import GateClient, GateCryptoPriceSource

__all__ = [
    "CoinGeckoClient",
    "CoinGeckoGlobalSource",
    "CoinGeckoPriceSource",
    "CoinMarketCapClient",
    "CoinMarketCapGlobalSource",
    "CoinMarketCapSnapshots",
    "GateClient",
    "GateCryptoPriceSource",
    "aggregate_snapshots",
]
