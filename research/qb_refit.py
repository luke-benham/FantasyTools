import json,math,statistics as st,sys
exec(open('calibrate.py').read().split('def pav_decreasing')[0])   # builds pts_rows[pos] = [(pos_ecr, ppw)]
def pav(y,w):
    out=[]
    for v,ww in zip(y,w):
        out.append([v,ww,1])
        while len(out)>1 and out[-2][0]<out[-1][0]:
            v2,w2,n2=out.pop(); v1,w1,n1=out.pop(); out.append([(v1*w1+v2*w2)/(w1+w2),w1+w2,n1+n2])
    r=[]
    for v,w,n in out: r+=[v]*n
    return r
def fit(pos,maxr,bw):
    data=[(e,v) for e,v in pts_rows[pos] if e<=maxr*1.3]
    grid=[1+i*0.5 for i in range(int((maxr-1)/0.5)+1)]
    sm,wt=[],[]
    for g in grid:
        num=den=0
        for e,v in data:
            k=math.exp(-0.5*((math.log(e)-math.log(g))/bw)**2); num+=k*v; den+=k
        sm.append(num/den); wt.append(den)
    f=pav(sm,wt)
    # break PAV ties with a gentle slope so rank order is preserved (max 0.02 pts per half-rank)
    for i in range(1,len(f)): f[i]=min(f[i],f[i-1]-0.02)
    return grid,f
cal=json.load(open('/home/claude/fantasytools/engine/calibration.json'))
for pos,maxr,bw in (('QB',40,0.30),('TE',45,0.30)):
    g,f=fit(pos,maxr,bw)
    old=cal['ros_curve'][pos]
    show=[1,2,3,5,8,10,12,15,20,24,30]
    print(pos,'new',' '.join(f"{r}:{f[g.index(r)]:.1f}" for r in show if r in g))
    print(pos,'old',' '.join(f"{r}:{old['ppw'][old['rank'].index(r)]:.1f}" for r in show if r in old['rank']))
    if pos=='QB' or '--te' in sys.argv:
        cal['ros_curve'][pos]={"rank":g,"ppw":[round(x,3) for x in f],"method":f"kernel(log-rank,bw={bw})+isotonic, 2024-25","n":len(pts_rows[pos])}
cal['qb_stream_bonus']=2.5
cal['note']="fit on 2024-25; QB refit 2026-10-08 (isotonic, flatter top); see research/calibrate.py and research/qb_study.py"
json.dump(cal,open('/home/claude/fantasytools/engine/calibration.json','w'),indent=1)
