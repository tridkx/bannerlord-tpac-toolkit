"""Port of the C# LZ4 encoder, so the bug can be found quickly."""
import random
import lz4.block


def encode(input, offset=0, length=None):
    MIN_MATCH = 4
    LAST_LITERALS = 5
    MF_LIMIT = 12
    HASH_LOG = 16
    HASH_SIZE = 1 << HASH_LOG
    MAX_DISTANCE = 65535
    if length is None:
        length = len(input) - offset

    out = bytearray()
    table = [-1] * HASH_SIZE
    anchor = offset
    ip = offset
    iend = offset + length
    mflimit = iend - MF_LIMIT

    def read_u32(i):
        return int.from_bytes(input[i:i + 4], "little")

    if length >= MF_LIMIT:
        while ip < mflimit:
            seq = read_u32(ip)
            h = ((seq * 2654435761) & 0xFFFFFFFF) >> (32 - HASH_LOG)
            candidate = table[h]
            table[h] = ip
            if candidate < 0 or ip - candidate > MAX_DISTANCE or read_u32(candidate) != seq:
                ip += 1
                continue
            match_len = 0
            max_len = iend - LAST_LITERALS - ip
            while match_len < max_len and input[candidate + match_len] == input[ip + match_len]:
                match_len += 1
            if match_len < MIN_MATCH:
                ip += 1
                continue

            lit_len = ip - anchor
            token_pos = len(out)
            out.append(0)
            token = 0
            if lit_len >= 15:
                token |= 0x0F << 4
                rem = lit_len - 15
                while rem >= 255:
                    out.append(255)
                    rem -= 255
                out.append(rem)
            else:
                token |= lit_len << 4
            out += input[anchor:anchor + lit_len]

            match_code = match_len - MIN_MATCH
            if match_code >= 15:
                token |= 0x0F
            else:
                token |= match_code

            # offset comes BEFORE the match-length extension bytes
            offs = ip - candidate
            out.append(offs & 0xFF)
            out.append((offs >> 8) & 0xFF)

            if match_code >= 15:
                rem = match_code - 15
                while rem >= 255:
                    out.append(255)
                    rem -= 255
                out.append(rem)
            out[token_pos] = token

            ip += match_len
            anchor = ip

    # final literals
    lit_len = iend - anchor
    token_pos = len(out)
    out.append(0)
    token = 0
    if lit_len >= 15:
        token |= 0x0F << 4
        rem = lit_len - 15
        while rem >= 255:
            out.append(255)
            rem -= 255
        out.append(rem)
    else:
        token |= lit_len << 4
    out += input[anchor:iend]
    out[token_pos] = token
    return bytes(out)


def trace_decode(data, expected_len):
    sp, dp = 0, 0
    steps = 0
    while sp < len(data):
        token = data[sp]; sp += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = data[sp]; sp += 1; lit += b
                if b != 255:
                    break
        dp += lit
        sp += lit
        if dp >= expected_len:
            return dp, steps, "ok-final-literals"
        if sp + 2 > len(data):
            return dp, steps, f"TRUNCATED at token {steps} (need offset, sp={sp}, len={len(data)})"
        off = data[sp] | (data[sp + 1] << 8); sp += 2
        ml = token & 0x0F
        if ml == 15:
            while True:
                b = data[sp]; sp += 1; ml += b
                if b != 255:
                    break
        ml += 4
        dp += ml
        steps += 1
        if dp > expected_len:
            return dp, steps, f"OVERFLOW at token {steps}"
    return dp, steps, "ran out of input"


if __name__ == "__main__":
    random.seed(7)
    tests = {
        "aaaa": b"a" * 1000,
        "repeat": (b"hello world " * 200),
        "random": bytes(random.randrange(256) for _ in range(5000)),
        "mixed": bytes(random.randrange(256) for _ in range(100)) + b"z" * 4000 + bytes(random.randrange(256) for _ in range(100)),
    }
    for name, data in tests.items():
        enc = encode(data)
        dp, steps, status = trace_decode(enc, len(data))
        try:
            dec = lz4.block.decompress(enc, uncompressed_size=len(data))
            ok = dec == data
        except Exception as e:
            ok = f"lz4 error: {e}"
        print(f"{name:<8} in={len(data):6d} out={len(enc):6d} match={ok} trace={status} dp={dp}")
