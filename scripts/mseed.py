"""Minimal miniSEED 2 reader (numpy only): Steim1, Steim2, int16, int32, float32, float64.

read(buf) -> dict {"NET.STA.LOC.CHA": (t0_epoch, sample_rate, np.ndarray float64)}, one continuous trace per
channel on a regular grid starting at the earliest record; gaps are NaN.
"""

import struct
from datetime import datetime, timezone

import numpy as np


def _btime(b, e):
    yr, doy, hh, mm, ss, _, frac = struct.unpack(e + "HHBBBBH", b)
    return datetime(yr, 1, 1, tzinfo=timezone.utc).timestamp() + (doy - 1) * 86400 + hh * 3600 + mm * 60 + ss + frac * 1e-4


def _rate(f, m):
    r = float(f) if f > 0 else (-1.0 / f if f < 0 else 0.0)
    return r * m if m > 0 else (-r / m if m < 0 else r)


def _sx(v, bits):
    """Sign-extend unsigned ints v of the given bit width."""
    v = v.astype(np.int64)
    return np.where(v >= 1 << (bits - 1), v - (1 << bits), v)


def _steim(data, n, level, e):
    words = np.frombuffer(data[:len(data) // 64 * 64], dtype=e + "u4").reshape(-1, 16).astype(np.int64)
    if not len(words):
        return np.zeros(0)
    x0 = _sx(words[0, 1:2], 32)[0]
    s8, s16 = ((24, 16, 8, 0), (16, 0)) if e == ">" else ((0, 8, 16, 24), (0, 16))   # bytes/halfwords keep memory order
    diffs = []
    for f, fr in enumerate(words):
        ctrl = int(fr[0])
        for i in range(1 if f else 3, 16):
            c, w = (ctrl >> (30 - 2 * i)) & 3, int(fr[i])
            if c == 0:
                continue
            if c == 1:                                    # 4 x 8 bit
                diffs += [_sx(np.array([(w >> s) & 0xFF]), 8)[0] for s in s8]
            elif level == 1:
                if c == 2:
                    diffs += [_sx(np.array([(w >> s) & 0xFFFF]), 16)[0] for s in s16]
                else:
                    diffs.append(_sx(np.array([w]), 32)[0])
            else:
                dn = w >> 30
                if c == 2:
                    spec = {1: (1, 30), 2: (2, 15), 3: (3, 10)}.get(dn)
                else:
                    spec = {0: (5, 6), 1: (6, 5), 2: (7, 4)}.get(dn)
                if spec is None:
                    continue
                k, bits = spec
                mask = (1 << bits) - 1
                diffs += list(_sx(np.array([(w >> (bits * (k - 1 - j))) & mask for j in range(k)]), bits))
    d = np.asarray(diffs[1:n], dtype=np.int64)            # first difference refers to the previous record
    return np.concatenate([[x0], x0 + np.cumsum(d)]).astype(np.float64)[:n]


def _records(buf):
    pos = 0
    while pos + 48 <= len(buf):
        h = buf[pos:pos + 48]
        e = ">" if 1900 < struct.unpack(">H", h[20:22])[0] < 2100 else "<"
        sta, loc, cha, net = (h[a:b].decode("ascii", "replace").strip() for a, b in ((8, 13), (13, 15), (15, 18), (18, 20)))
        t0 = _btime(h[20:30], e)
        ns, rf, rm = struct.unpack(e + "Hhh", h[30:36])
        act, nblk = h[36], h[39]
        tcorr, doff, boff = struct.unpack(e + "iHH", h[40:48])
        enc, reclen, word_e = 10, 512, e
        while boff and pos + boff + 4 <= len(buf):
            btype, bnext = struct.unpack(e + "HH", buf[pos + boff:pos + boff + 4])
            if btype == 1000:
                enc, wo, rl = buf[pos + boff + 4], buf[pos + boff + 5], buf[pos + boff + 6]
                reclen, word_e = 1 << rl, (">" if wo else "<")
            elif btype == 1001:
                t0 += struct.unpack("b", buf[pos + boff + 5:pos + boff + 6])[0] * 1e-6
            boff = bnext
        if not act & 2:
            t0 += tcorr * 1e-4
        yield f"{net}.{sta}.{loc}.{cha}", t0, _rate(rf, rm), ns, enc, word_e, buf[pos + doff:pos + reclen] if doff else b""
        pos += reclen


def _decode(enc, e, data, n):
    if enc == 10:
        return _steim(data, n, 1, e)
    if enc == 11:
        return _steim(data, n, 2, e)
    dt = {1: "i2", 3: "i4", 4: "f4", 5: "f8"}.get(enc)
    if dt is None:
        raise ValueError(f"unsupported miniSEED encoding {enc}")
    return np.frombuffer(data, dtype=e + dt, count=n).astype(np.float64)


def read(buf):
    segs = {}
    for sid, t0, sr, ns, enc, e, data in _records(buf):
        if ns and sr > 0:
            segs.setdefault(sid, []).append((t0, sr, _decode(enc, e, data, ns)))
    out = {}
    for sid, ss in segs.items():
        sr = ss[0][1]
        ss = [s for s in ss if abs(s[1] - sr) < 1e-6 * sr]
        start = min(s[0] for s in ss)
        npts = max(int(round((s[0] - start) * sr)) + len(s[2]) for s in ss)
        y = np.full(npts, np.nan)
        for t0, _, d in ss:
            i = int(round((t0 - start) * sr))
            y[i:i + len(d)] = d
        out[sid] = (start, sr, y)
    return out
