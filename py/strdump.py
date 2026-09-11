import re,sys
p=sys.argv[1]
data=open(p,'rb').read()
pats=[k.encode() for k in sys.argv[2:]] or [b'Asset']
strs=re.findall(rb'[\x20-\x7e]{4,120}',data)
out=[]
for s in strs:
    for k in pats:
        if k in s:
            out.append(s.decode('latin1')); break
seen=set(); res=[]
for s in out:
    if s not in seen:
        seen.add(s); res.append(s)
print(len(res))
for s in res: print(s)
