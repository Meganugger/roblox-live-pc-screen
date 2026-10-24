"""Agent research tool: minimal Roblox binary place/model (.rbxl/.rbxm) reader.

Dumps every Script / LocalScript / ModuleScript `Source` (with its instance path) so third-party places can be
reviewed as text. Handles LZ4 and zstd chunks; parses INST (classes + referents), PROP (`Name`, `Source` strings) and
PRNT (parents). Usage: python3 scripts/agent/rbxl_dump_scripts.py place.rbxl OUTDIR
Not part of the runtime system. Written for T-0004 (ScreenBlox v4.7.rbxl: 96 classes, 225 instances parsed OK).
"""
import struct, sys, os, lz4.block
def rd_str(b,o):
    n=struct.unpack_from('<I',b,o)[0]; return b[o+4:o+4+n], o+4+n
def interleaved_i32(b,o,cnt):
    v=[]
    for i in range(cnt):
        x=(b[o+i]<<24)|(b[o+cnt+i]<<16)|(b[o+2*cnt+i]<<8)|b[o+3*cnt+i]
        v.append((x>>1)^-(x&1))
    return v,o+4*cnt
def refs(b,o,cnt):
    v,o=interleaved_i32(b,o,cnt); acc=0; out=[]
    for x in v: acc+=x; out.append(acc)
    return out,o
data=open(sys.argv[1],'rb').read(); outdir=sys.argv[2]
assert data[:8]==b'<roblox!', data[:8]
ncls,ninst=struct.unpack_from('<ii',data,16); pos=32
classes={}; inst_class={}; props={}; parent={}
while pos<len(data):
    name=data[pos:pos+4]; clen,ulen,_=struct.unpack_from('<III',data,pos+4); pos+=16
    if clen==0: p=data[pos:pos+ulen]; pos+=ulen
    else:
        raw=data[pos:pos+clen]; pos+=clen
        if raw[:4]==b'\x28\xb5\x2f\xfd':
            import zstandard; p=zstandard.ZstdDecompressor().decompress(raw,max_output_size=ulen)
        else: p=lz4.block.decompress(raw,uncompressed_size=ulen)
    if name==b'INST':
        cid=struct.unpack_from('<I',p,0)[0]; cn,o=rd_str(p,4); o+=1; cnt=struct.unpack_from('<I',p,o)[0]; o+=4
        r,o=refs(p,o,cnt); classes[cid]=(cn.decode(),r)
        for x in r: inst_class[x]=cn.decode()
    elif name==b'PROP':
        cid=struct.unpack_from('<I',p,0)[0]; pn,o=rd_str(p,4); t=p[o]; o+=1; pn=pn.decode()
        if pn in ('Name','Source') :
            cn,r=classes[cid]
            if t==1:
                for x in r:
                    s,o=rd_str(p,o); props.setdefault(x,{})[pn]=s.decode('utf-8','replace')
            else: print('type',t,'for',cn,pn)
    elif name==b'PRNT':
        cnt=struct.unpack_from('<I',p,1)[0]; ch,o=refs(p,5,cnt); pa,o=refs(p,o,cnt)
        parent.update(zip(ch,pa))
    elif name==b'END\x00': break
def path(x):
    parts=[]
    while x is not None and x!=-1 and x in inst_class:
        parts.append(props.get(x,{}).get('Name',inst_class[x])); x=parent.get(x)
    return '/'.join(reversed(parts))
print('classes',ncls,'instances',ninst)
from collections import Counter
print(Counter(inst_class.values()).most_common(25))
os.makedirs(outdir,exist_ok=True)
for x,c in inst_class.items():
    if c in ('Script','LocalScript','ModuleScript'):
        src=props.get(x,{}).get('Source','')
        fn=os.path.join(outdir,(path(x).replace('/','__') or str(x))+'.'+c+'.lua')
        open(fn,'w').write(src); print(f'{c:12} {len(src):6d}  {path(x)}')
