import socket

import pytest


@pytest.mark.parametrize("missing_af_unix", [False, True])
def test_network_isolation_allows_loopback_without_requiring_af_unix(monkeypatch, missing_af_unix):
    if missing_af_unix:
        monkeypatch.delattr(socket, "AF_UNIX", raising=False)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(listener.getsockname())
            assert connection.getpeername() == listener.getsockname()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocked:
        with pytest.raises(RuntimeError, match="External network disabled"):
            blocked.connect(("203.0.113.1", 443))
