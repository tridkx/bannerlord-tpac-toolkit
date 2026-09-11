import sys,struct
def dump(p, n=256):
    d=open(p,'rb').read(n)
    print("FILE:",p)
    print(" first 64 hex:", d[:64].hex())
    print(" u32s:", struct.unpack('<16I', d[:64]))
    print(" ascii:", ''.join(chr(c) if 32<=c<127 else '.' for c in d[:n]))
    print()
for p in sys.argv[1:]:
    try: dump(p)
    except Exception as e: print(p,"ERR",e)
