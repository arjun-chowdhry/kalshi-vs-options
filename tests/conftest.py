"""No test may reach the network: every outbound connection or DNS lookup fails loudly.

Same guard as options-desk's tests/conftest.py. Loopback stays open (Windows asyncio uses it).
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pandas as pd
import pytest
from optdesk.data.rates import RateCurve

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", None}


def _refuse(target: object) -> None:
    raise RuntimeError(f"network access is disabled in tests (tried to reach {target!r})")


@pytest.fixture(scope="session", autouse=True)
def no_network():
    connect, getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def guarded_connect(sock, address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] not in LOCAL_HOSTS:
            _refuse(address)
        return connect(sock, address, *args, **kwargs)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in LOCAL_HOSTS:
            _refuse(host)
        return getaddrinfo(host, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(socket.socket, "connect", guarded_connect)
        mp.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
        yield


SPX_FIXTURE = Path(__file__).parent / "fixtures" / "spx_0dte_2026-11-05T142350"


@pytest.fixture(scope="session")
def spx_snapshot():
    """``(raw same-day chain, rate curve, meta)`` from snapshot 2026-11-05T142350.

    The real chain whose put quotes were corrupted (see kvo.options): the regression case.
    """
    raw = pd.read_csv(SPX_FIXTURE.with_suffix(".csv"), parse_dates=["asof", "last_trade", "expiry"])
    meta = json.loads(SPX_FIXTURE.with_suffix(".json").read_text())
    return raw, RateCurve.from_dict(meta["rate_curve"]), meta
