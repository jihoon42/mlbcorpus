"""상대 팀 기사 공출현 네트워크 (예비). 노드=선수, 엣지=같은 리캡 본문에 함께 언급(n_body>0), 같은 팀 엣지 제외."""
import json, time, itertools, collections
import pandas as pd, networkx as nx
t0=time.time()
pg=pd.read_csv("data/tables/player_game.csv.gz", usecols=["game_pk","season","team","player_id","full_name","n_body","in_headline"])
pg=pg[pg.n_body>0]
names=pg.groupby("player_id").full_name.last().to_dict()
out={}
for season,g in pg.groupby("season"):
    w=collections.Counter()
    for gpk,gg in g.groupby("game_pk"):
        teams=gg.groupby("team").player_id.apply(list).to_dict()
        if len(teams)<2: continue
        (ta,pa),(tb,pb)=list(teams.items())[:2]
        for a in pa:
            for b in pb:
                w[(min(a,b),max(a,b))]+=1
    G=nx.Graph()
    for (a,b),c in w.items(): G.add_edge(a,b,weight=c)
    deg=dict(G.degree(weight="weight"))      # 상대 팀 선수와 함께 언급된 횟수 합
    ndeg=dict(G.degree())                    # 서로 다른 상대 팀 선수 수
    try: eig=nx.eigenvector_centrality(G,weight="weight",max_iter=2000)
    except Exception as e: eig={k:0 for k in G}
    top=sorted(deg,key=deg.get,reverse=True)[:10]
    rank=sorted(deg,key=deg.get,reverse=True)
    ohtani=660271
    out[int(season)]=dict(nodes=G.number_of_nodes(),edges=G.number_of_edges(),
        top10=[(names[p],int(deg[p]),int(ndeg[p]),round(eig.get(p,0),3)) for p in top],
        ohtani=dict(rank=(rank.index(ohtani)+1) if ohtani in deg else None,deg=int(deg.get(ohtani,0)),ndeg=int(ndeg.get(ohtani,0)),eig_rank=(sorted(eig,key=eig.get,reverse=True).index(ohtani)+1) if ohtani in eig else None),
        eig_top5=[(names[p],round(eig[p],3)) for p in sorted(eig,key=eig.get,reverse=True)[:5]])
    print(season,out[int(season)]["nodes"],out[int(season)]["edges"],out[int(season)]["top10"][:5],out[int(season)]["ohtani"],f"{time.time()-t0:.0f}s",flush=True)
json.dump(out,open("data/tables/net_quick.json","w"),ensure_ascii=False,indent=1)
