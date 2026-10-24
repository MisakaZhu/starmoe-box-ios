"""Rijndael 块大小 256 位（Nb=8），移植自 StarMoe Box 的 crypto/Rijndael.kt。非 AES。"""
NB = 8
BLOCK = 32
_SHIFTS = (0, 1, 3, 4)


def _xtime(x):
    return ((x << 1) ^ (0x1B if x & 0x80 else 0)) & 0xFF


def _gmul(a, b):
    p = 0
    while b:
        if b & 1:
            p ^= a
        a = _xtime(a)
        b >>= 1
    return p


SBOX = [0] * 256
_p = _q = 1
while True:
    _p = (_p ^ (_p << 1) ^ (0x1B if _p & 0x80 else 0)) & 0xFF
    _q ^= _q << 1; _q ^= _q << 2; _q ^= _q << 4; _q &= 0xFF
    if _q & 0x80:
        _q ^= 0x09
    _r = lambda x, s: ((x << s) | (x >> (8 - s))) & 0xFF
    SBOX[_p] = (_q ^ _r(_q, 1) ^ _r(_q, 2) ^ _r(_q, 3) ^ _r(_q, 4) ^ 0x63) & 0xFF
    if _p == 1:
        break
SBOX[0] = 0x63
INV = [0] * 256
for _i in range(256):
    INV[SBOX[_i]] = _i
M = {f: [_gmul(i, f) for i in range(256)] for f in (2, 3, 9, 11, 13, 14)}


class Rijndael256:
    def __init__(self, key: bytes):
        assert len(key) in (16, 24, 32)
        nk = len(key) // 4
        self.nr = max(nk, NB) + 6
        words = NB * (self.nr + 1)
        w = bytearray(words * 4)
        w[: len(key)] = key
        rcon = 1
        for i in range(nk, words):
            t = list(w[4 * (i - 1): 4 * i])
            if i % nk == 0:
                t = [SBOX[t[1]] ^ rcon, SBOX[t[2]], SBOX[t[3]], SBOX[t[0]]]
                rcon = _xtime(rcon)
            elif nk > 6 and i % nk == 4:
                t = [SBOX[x] for x in t]
            for k in range(4):
                w[4 * i + k] = w[4 * (i - nk) + k] ^ t[k]
        self.rk = bytes(w)

    def _ark(self, s, r):
        b = r * BLOCK
        for i in range(BLOCK):
            s[i] ^= self.rk[b + i]

    def decrypt_block(self, blk):
        s = list(blk)
        self._ark(s, self.nr)
        for rnd in range(self.nr, -1, -1):
            if rnd == self.nr:
                continue
            # invShiftRows
            for r in range(1, 4):
                tmp = [0] * NB
                for c in range(NB):
                    tmp[(c + _SHIFTS[r]) % NB] = s[r + 4 * c]
                for c in range(NB):
                    s[r + 4 * c] = tmp[c]
            s = [INV[x] for x in s]
            self._ark(s, rnd)
            if rnd:
                for c in range(NB):
                    i = 4 * c
                    a0, a1, a2, a3 = s[i:i + 4]
                    s[i] = M[14][a0] ^ M[11][a1] ^ M[13][a2] ^ M[9][a3]
                    s[i + 1] = M[9][a0] ^ M[14][a1] ^ M[11][a2] ^ M[13][a3]
                    s[i + 2] = M[13][a0] ^ M[9][a1] ^ M[14][a2] ^ M[11][a3]
                    s[i + 3] = M[11][a0] ^ M[13][a1] ^ M[9][a2] ^ M[14][a3]
        return bytes(s)

    def encrypt_block(self, blk):
        s = list(blk)
        self._ark(s, 0)
        for rnd in range(1, self.nr + 1):
            s = [SBOX[x] for x in s]
            for r in range(1, 4):
                tmp = [s[r + 4 * ((c + _SHIFTS[r]) % NB)] for c in range(NB)]
                for c in range(NB):
                    s[r + 4 * c] = tmp[c]
            if rnd != self.nr:
                for c in range(NB):
                    i = 4 * c
                    a0, a1, a2, a3 = s[i:i + 4]
                    s[i] = M[2][a0] ^ M[3][a1] ^ a2 ^ a3
                    s[i + 1] = a0 ^ M[2][a1] ^ M[3][a2] ^ a3
                    s[i + 2] = a0 ^ a1 ^ M[2][a2] ^ M[3][a3]
                    s[i + 3] = M[3][a0] ^ a1 ^ a2 ^ M[2][a3]
            self._ark(s, rnd)
        return bytes(s)

    def decrypt_cbc(self, data, iv):
        out = bytearray()
        prev = iv
        for o in range(0, len(data), BLOCK):
            c = data[o:o + BLOCK]
            out += bytes(a ^ b for a, b in zip(self.decrypt_block(c), prev))
            prev = c
        return bytes(out)

    def encrypt_cbc(self, data, iv):
        out = bytearray()
        prev = iv
        for o in range(0, len(data), BLOCK):
            prev = self.encrypt_block(bytes(a ^ b for a, b in zip(data[o:o + BLOCK], prev)))
            out += prev
        return bytes(out)
