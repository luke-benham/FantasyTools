import csv,glob,os,json,math,collections,statistics as st
from bt_common import load_season, ids
rows=[]   # (season, week, pos_ecr, ppw_actual, sid)
streams=collections.defaultdict(list)
for Y in (2024,2025):
    gameday,stats,proj=load_season(Y)
    pts=lambda w,s:(stats[w].get(s) or {}).get('pts_ppr') or 0.0
    snaps=[]
    if Y==2024:
        wk={"2024-09-27":4,"2024-10-04":5,"2024-10-11":6,"2024-10-18":7,"2024-10-25":8,"2024-11-01":9,"2024-11-08":10,"2024-11-15":11,"2024-11-22":12,"2024-11-27":13,"2024-12-06":14}
        by=collections.defaultdict(list)
        for r in csv.DictReader(open('ecr2024.csv')):
            if r['date'] in wk and r['page_type']=='redraft-qb': by[r['date']].append((r['id'],float(r['ecr'])))
        snaps=[(wk[d],v) for d,v in by.items()]
    else:
        for f in sorted(glob.glob('ros2025/*.csv')):
            d=os.path.basename(f)[:10]
            w=next((k for k in range(1,18) if min(gameday[k].values())<=d<=max(gameday[k].values())),None)
            if not w or w>14: continue
            v=[(x['id'],float(x['ecr'])) for x in csv.DictReader(open(f)) if x['page_type']=='redraft-qb' and 'ros-' in x['fp_page']]
            if v: snaps.append((w,v))
    for w,v in snaps:
        n=17-w
        for fid,e in v:
            s=ids.get(fid)
            if s: rows.append((Y,w,e,sum(pts(k,s) for k in range(w+1,18))/n,s))
        # streaming: QBs ranked beyond cut (likely free) -> each future week pick best Rotowire projection, take actual
        for cut in (10,12,16):
            free=[ids[f] for f,e in v if e>cut and f in ids]
            got=[]
            for k in range(w+1,18):
                cand=[(proj[k].get(s,(0,))[0],s) for s in free]
                if not cand: continue
                best=max(cand)[1]; got.append(pts(k,best))
            # compare with: the 3 best-ranked free QBs' ROS ppw avg (hold strategy)
            hold=sorted(((e,ids[f]) for f,e in v if e>cut and f in ids))[:3]
            hp=st.mean(sum(pts(k,s) for k in range(w+1,18))/n for _,s in hold) if hold else 0
            streams[cut].append((st.mean(got) if got else 0, hp))
bins=[(1,1.5),(1.5,2.5),(2.5,4),(4,6),(6,8),(8,10),(10,12),(12,15),(15,20),(20,26)]
print('QB realized pts per remaining week by ROS positional ECR (2024-25):')
for a,b in bins:
    xs=[r[3] for r in rows if a<=r[2]<b]
    if xs: print(f'  QB{a:g}-{b:g}: {st.mean(xs):5.1f}  n={len(xs)}')
for cut,v in streams.items():
    print(f'free QBs beyond QB{cut}: stream best weekly projection {st.mean(x for x,_ in v):.1f} vs hold top-3 free {st.mean(y for _,y in v):.1f}')
