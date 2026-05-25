"""Pure-Python technical indicator calculations.

Covers the MVP technical factors required by PRD §4.1 (`docs/PRD.md`):
均线 / MACD / KDJ / RSI / 布林带 / 量价.  All calculations operate on
plain ``list[float]`` price/volume series so the module stays dependency
free (consistent with the rest of the strategy core).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


def _check_series(series: Sequence[float], name: str) -> None:
    if series is None:
        raise ValueError(f"{name} series is required")
    if not isinstance(series, Sequence) or isinstance(series, (str, bytes)):
        raise TypeError(f"{name} series must be a sequence of floats")


def simple_moving_average(series: Sequence[float], window: int) -> list[float | None]:
    """Return SMA aligned with ``series``; first ``window-1`` values are ``None``."""

    _check_series(series, "price")
    if window <= 0:
        raise ValueError("window must be positive")
    result: list[float | None] = []
    running = 0.0
    for index, value in enumerate(series):
        running += value
        if index >= window:
            running -= series[index - window]
        if index >= window - 1:
            result.append(running / window)
        else:
            result.append(None)
    return result


def exponential_moving_average(series: Sequence[float], window: int) -> list[float | None]:
    """Return EMA aligned with ``series``."""

    _check_series(series, "price")
    if window <= 0:
        raise ValueError("window must be positive")
    if not series:
        return []
    alpha = 2.0 / (window + 1)
    result: list[float | None] = []
    ema: float | None = None
    for index, value in enumerate(series):
        if ema is None:
            ema = float(value)
        else:
            ema = alpha * value + (1 - alpha) * ema
        # EMA is meaningful from index >= window - 1 for parity with SMA
        result.append(ema if index >= window - 1 else None)
    return result


@dataclass(frozen=True)
class MACDPoint:
    """Single point of an MACD series."""

    dif: float | None
    dea: float | None
    hist: float | None


def macd(
    series: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> list[MACDPoint]:
    """Return MACD line (DIF), signal (DEA) and histogram (2*(DIF-DEA))."""

    _check_series(series, "price")
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("MACD periods must be positive")
    if fast >= slow:
        raise ValueError("fast period must be smaller than slow")
    fast_ema = exponential_moving_average(series, fast)
    slow_ema = exponential_moving_average(series, slow)
    dif: list[float | None] = []
    for f, s in zip(fast_ema, slow_ema):
        if f is None or s is None:
            dif.append(None)
        else:
            dif.append(f - s)
    # DEA is EMA(signal) of DIF; skip Nones at the head
    dea: list[float | None] = [None] * len(series)
    valid_dif = [(index, value) for index, value in enumerate(dif) if value is not None]
    if valid_dif:
        alpha = 2.0 / (signal + 1)
        ema: float | None = None
        first_index = valid_dif[0][0]
        for index, value in valid_dif:
            ema = value if ema is None else alpha * value + (1 - alpha) * ema
            if index - first_index >= signal - 1:
                dea[index] = ema
    return [
        MACDPoint(
            dif=d,
            dea=e,
            hist=None if d is None or e is None else 2.0 * (d - e),
        )
        for d, e in zip(dif, dea)
    ]


def relative_strength_index(series: Sequence[float], window: int = 14) -> list[float | None]:
    """Return RSI(0–100) using Wilder's smoothing method."""

    _check_series(series, "price")
    if window <= 0:
        raise ValueError("window must be positive")
    rsi: list[float | None] = [None] * len(series)
    if len(series) <= window:
        return rsi
    gains = 0.0
    losses = 0.0
    for i in range(1, window + 1):
        change = series[i] - series[i - 1]
        if change >= 0:
            gains += change
        else:
            losses -= change
    avg_gain = gains / window
    avg_loss = losses / window
    rsi[window] = _rsi_from_avg(avg_gain, avg_loss)
    for i in range(window + 1, len(series)):
        change = series[i] - series[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (window - 1) + gain) / window
        avg_loss = (avg_loss * (window - 1) + loss) / window
        rsi[i] = _rsi_from_avg(avg_gain, avg_loss)
    return rsi


def _rsi_from_avg(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


@dataclass(frozen=True)
class KDJPoint:
    """KDJ indicator value at a single timestamp."""

    k: float | None
    d: float | None
    j: float | None


def kdj(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    window: int = 9,
) -> list[KDJPoint]:
    """Compute KDJ (Stochastic) with the conventional 9/3/3 smoothing."""

    _check_series(highs, "high")
    _check_series(lows, "low")
    _check_series(closes, "close")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("high/low/close must have equal length")
    if window <= 0:
        raise ValueError("window must be positive")
    n = len(closes)
    output: list[KDJPoint] = [KDJPoint(None, None, None)] * n
    prev_k = 50.0
    prev_d = 50.0
    for i in range(n):
        if i < window - 1:
            continue
        hh = max(highs[i - window + 1 : i + 1])
        ll = min(lows[i - window + 1 : i + 1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100.0
        k = (2.0 / 3.0) * prev_k + (1.0 / 3.0) * rsv
        d = (2.0 / 3.0) * prev_d + (1.0 / 3.0) * k
        j = 3.0 * k - 2.0 * d
        output[i] = KDJPoint(k=k, d=d, j=j)
        prev_k, prev_d = k, d
    return output


@dataclass(frozen=True)
class BollingerPoint:
    """Bollinger band sample at a single timestamp."""

    middle: float | None
    upper: float | None
    lower: float | None


def bollinger_bands(
    series: Sequence[float],
    window: int = 20,
    num_std: float = 2.0,
) -> list[BollingerPoint]:
    """Compute Bollinger bands using SMA + sample standard deviation."""

    _check_series(series, "price")
    if window <= 1:
        raise ValueError("window must be at least 2")
    if num_std <= 0:
        raise ValueError("num_std must be positive")
    middles = simple_moving_average(series, window)
    out: list[BollingerPoint] = []
    for index in range(len(series)):
        mid = middles[index]
        if mid is None:
            out.append(BollingerPoint(None, None, None))
            continue
        window_slice = series[index - window + 1 : index + 1]
        variance = sum((value - mid) ** 2 for value in window_slice) / (window - 1)
        std = variance**0.5
        out.append(
            BollingerPoint(middle=mid, upper=mid + num_std * std, lower=mid - num_std * std)
        )
    return out


def volume_ratio(
    volumes: Sequence[float],
    window: int = 5,
) -> list[float | None]:
    """Ratio of latest volume to its trailing ``window`` average (量比)."""

    _check_series(volumes, "volume")
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[float | None] = [None] * len(volumes)
    for index in range(window, len(volumes)):
        baseline = sum(volumes[index - window : index]) / window
        out[index] = None if baseline == 0 else volumes[index] / baseline
    return out


def ma_trend_score(
    series: Sequence[float],
    short_window: int = 5,
    mid_window: int = 20,
    long_window: int = 60,
) -> int | None:
    """Return ``1`` for 多头排列, ``-1`` for 空头排列, ``0`` otherwise."""

    short = simple_moving_average(series, short_window)
    mid = simple_moving_average(series, mid_window)
    long = simple_moving_average(series, long_window)
    if not series:
        return None
    last = len(series) - 1
    s, m, l = short[last], mid[last], long[last]
    if s is None or m is None or l is None:
        return None
    if s > m > l:
        return 1
    if s < m < l:
        return -1
    return 0
