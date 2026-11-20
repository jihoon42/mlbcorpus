"""headline 예측 모델 + 집중도 + 서사 프리미엄 계산.

입력: data/tables/player_game.csv.gz, games.csv.gz (analysis/build_player_game.py 출력을 합친 것)
출력: data/tables/results.json, data/tables/oof_predictions.csv.gz
사용: python3 analysis/run_model.py  (리포 루트에서; pandas, scikit-learn, lightgbm 필요)
"""
import json, sys, time, warnings
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score, average_precision_score, log_loss
import lightgbm as lgb

warnings.filterwarnings("ignore")
t0 = time.time()
pg = pd.read_csv("data/tables/player_game.csv.gz")
g = pd.read_csv("data/tables/games.csv.gz")
pg = pg[pg.headline_ambiguous == 0].copy()
pg["run_diff"] = pg.team_runs - pg.opp_runs
pg["wpa_total"] = pg.wpa_bat + pg.wpa_pit
pg["two_way"] = ((pg.pa > 0) & (pg.pitched == 1)).astype(int)
pg["pos_P"] = (pg.position == "P").astype(int)
pg["pos_DH"] = (pg.position == "DH").astype(int)
pg["qs"] = ((pg.outs >= 18) & (pg.p_er <= 3) & (pg.gs == 1)).astype(int)
pg["is_sp"] = (pg.gs == 1).astype(int)
# 경기 내 상대 순위 (한 경기에 headline 자리는 하나뿐이라 경쟁 구조가 중요)
grp = pg.groupby("game_pk")
pg["wpa_rank"] = grp.wpa_total.rank(ascending=False, method="min")
pg["hr_rank"] = grp.hr.rank(ascending=False, method="min")
pg["wpa_gap_to_best"] = grp.wpa_total.transform("max") - pg.wpa_total
pg["game_best_wpa"] = (pg.wpa_rank == 1).astype(int)
pg["game_max_hr"] = grp.hr.transform("max")
pg["date"] = pd.to_datetime(pg.date)
pg = pg.sort_values(["player_id", "date", "game_pk"]).reset_index(drop=True)

# 명성(관성) feature: 전년도 headline 수·경기 수, 같은 시즌 그 경기 이전까지의 headline 수 (누수 없음)
season_tot = pg.groupby(["player_id", "season"]).agg(hl=("in_headline", "sum"), gp=("in_headline", "size")).reset_index()
prev = season_tot.copy(); prev["season"] = prev.season + 1
prev = prev.rename(columns={"hl": "hl_prev", "gp": "gp_prev"})
pg = pg.merge(prev, on=["player_id", "season"], how="left")
pg["hl_prev_rate"] = pg.hl_prev / pg.gp_prev
pg["hl_todate"] = pg.groupby(["player_id", "season"]).in_headline.cumsum() - pg.in_headline
pg["gp_todate"] = pg.groupby(["player_id", "season"]).cumcount()
pg["hl_todate_rate"] = np.where(pg.gp_todate > 0, pg.hl_todate / pg.gp_todate.clip(lower=1), np.nan)

PERF = ["pa", "ab", "h", "d2", "d3", "hr", "rbi", "r", "bb", "so", "sb", "tb",
        "pitched", "is_sp", "outs", "bf", "p_k", "p_bb", "p_h", "p_hr", "p_er", "p_r", "pitches", "win", "loss", "save", "hold", "qs",
        "wpa_bat", "wpa_pit", "wpa_total", "n_pa_bat", "n_pa_pit", "max_li",
        "is_home", "team_won", "run_diff", "team_runs", "opp_runs", "is_starter_bat", "two_way", "pos_P", "pos_DH",
        "wpa_rank", "hr_rank", "wpa_gap_to_best", "game_best_wpa", "game_max_hr"]
FAME = ["hl_prev", "gp_prev", "hl_prev_rate", "hl_todate", "gp_todate", "hl_todate_rate"]
y = pg.in_headline.values
train = pg.season <= 2024
valid = pg.season == 2024
fit = pg.season <= 2023
test = pg.season >= 2025
print("rows", len(pg), "train", train.sum(), "test", test.sum(), f"{time.time()-t0:.0f}s")

def lgb_params():
    return dict(objective="binary", learning_rate=0.05, num_leaves=63, min_child_samples=200,
                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, n_jobs=8)

def fit_lgb(cols, rows_fit, rows_valid):
    dtr = lgb.Dataset(pg.loc[rows_fit, cols], y[rows_fit])
    dva = lgb.Dataset(pg.loc[rows_valid, cols], y[rows_valid])
    m = lgb.train(lgb_params(), dtr, num_boost_round=1500, valid_sets=[dva], callbacks=[lgb.early_stopping(50, verbose=False)])
    return m

def metrics(ytrue, p):
    return dict(auc=float(roc_auc_score(ytrue, p)), ap=float(average_precision_score(ytrue, p)), logloss=float(log_loss(ytrue, p)),
                base_rate=float(ytrue.mean()))

res = {"n_rows": int(len(pg)), "n_games": int(pg.game_pk.nunique()), "n_players": int(pg.player_id.nunique()),
       "label_rate": float(y.mean()), "train_seasons": "2019-2024", "test_seasons": "2025-2026"}

# ---------- 모델 P (성과만), 모델 P+F (성과+명성): LightGBM, 2019-23 학습 / 2024 early stop / 2025-26 평가 ----------
models = {}
for name, cols in (("P", PERF), ("PF", PERF + FAME)):
    m = fit_lgb(cols, fit, valid)
    p_test = m.predict(pg.loc[test, cols], num_iteration=m.best_iteration)
    models[name] = m
    res[f"lgb_{name}"] = dict(best_iter=int(m.best_iteration), test=metrics(y[test], p_test))
    imp = pd.Series(m.feature_importance("gain"), index=cols)
    imp = (imp / imp.sum()).sort_values(ascending=False)
    res[f"lgb_{name}"]["importance"] = [(k, float(v)) for k, v in imp.head(15).items()]
    print(name, res[f"lgb_{name}"]["test"], f"{time.time()-t0:.0f}s")

# 로지스틱 회귀 (해석용, 표준화 계수)
def fit_lr(cols):
    X = pg[cols].fillna(0)
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
    pipe.fit(X[train], y[train])
    p = pipe.predict_proba(X[test])[:, 1]
    coef = pd.Series(pipe[-1].coef_[0], index=cols).sort_values(key=abs, ascending=False)
    return metrics(y[test], p), [(k, float(v)) for k, v in coef.head(15).items()]
for name, cols in (("P", PERF), ("PF", PERF + FAME)):
    mt, coef = fit_lr(cols)
    res[f"lr_{name}"] = dict(test=mt, coef=coef)
    print("LR", name, mt, f"{time.time()-t0:.0f}s")

# ---------- 단순 기술통계: 리그는 무엇에 headline 을 주는가 ----------
def rate(mask):
    return dict(n=int(mask.sum()), rate=float(y[mask].mean()))
res["descriptive"] = {
    "all": rate(np.ones(len(pg), bool)),
    "hr>=2": rate(pg.hr >= 2), "hr==1": rate(pg.hr == 1), "hr==0,pa>0": rate((pg.hr == 0) & (pg.pa > 0)),
    "wpa_total>=30": rate(pg.wpa_total >= 30), "wpa 15-30": rate((pg.wpa_total >= 15) & (pg.wpa_total < 30)),
    "sp 7+IP <=1ER": rate((pg.is_sp == 1) & (pg.outs >= 21) & (pg.p_er <= 1)), "qs": rate(pg.qs == 1),
    "game_best_wpa": rate(pg.game_best_wpa == 1), "game_best_wpa & team_won": rate((pg.game_best_wpa == 1) & (pg.team_won == 1)),
    "game_best_wpa & team_lost": rate((pg.game_best_wpa == 1) & (pg.team_won == 0)),
    "team_won": rate(pg.team_won == 1), "team_lost": rate(pg.team_won == 0),
}
# 같은 성과 구간에서 명성에 따른 차이 (관성의 직관적 증거)
sub = pg[(pg.game_best_wpa == 1) & (pg.team_won == 1) & pg.hl_prev.notna()]
qs_ = sub.hl_prev.quantile([0.5, 0.9])
res["descriptive"]["best_wpa_won_by_fame"] = {
    "hl_prev==0": rate((pg.game_best_wpa == 1) & (pg.team_won == 1) & (pg.hl_prev == 0)),
    "hl_prev 1-9": rate((pg.game_best_wpa == 1) & (pg.team_won == 1) & (pg.hl_prev >= 1) & (pg.hl_prev < 10)),
    "hl_prev>=10": rate((pg.game_best_wpa == 1) & (pg.team_won == 1) & (pg.hl_prev >= 10)),
}

# ---------- 집중도 ----------
conc = []
for s, d in pg.groupby("season"):
    per = d.groupby("player_id").agg(hl=("in_headline", "sum"), gp=("in_headline", "size"), name=("full_name", "first"))
    tot = per.hl.sum()
    srt = per.hl.sort_values(ascending=False)
    n_players = (per.gp >= 1).sum()
    top1pct = int(np.ceil(n_players * 0.01))
    x = np.sort(per.hl.values.astype(float)); n = len(x)
    gini = float((2 * np.sum(np.arange(1, n + 1) * x) / (n * x.sum())) - (n + 1) / n) if x.sum() > 0 else None
    gs = g[g.season == s]
    oht = per.loc[660271].hl if 660271 in per.index else 0
    conc.append(dict(season=int(s), headlines=int(tot), games=int(d.game_pk.nunique()), n_players=int(n_players),
                     top10_share=float(srt.head(10).sum() / tot), top1pct_share=float(srt.head(top1pct).sum() / tot),
                     top1pct_n=top1pct, gini=gini, ohtani=int(oht), ohtani_share=float(oht / tot),
                     personalized_rate=float((gs.n_players_in_headline > 0).mean()),
                     top5=[(per.loc[i, "name"], int(per.loc[i, "hl"])) for i in srt.head(5).index]))
res["concentration"] = conc
for c in conc:
    print(c["season"], "hl", c["headlines"], "top10", round(c["top10_share"], 3), "gini", round(c["gini"], 3), "ohtani", c["ohtani"], c["top5"][:3])

# ---------- 서사 프리미엄: leave-one-season-out 예측 (모델 P) 으로 기대 headline 수 ----------
oof = np.zeros(len(pg))
n_iter = max(200, res["lgb_P"]["best_iter"])
for s in sorted(pg.season.unique()):
    tr = (pg.season != s).values; te = (pg.season == s).values
    m = lgb.train(lgb_params(), lgb.Dataset(pg.loc[tr, PERF], y[tr]), num_boost_round=n_iter)
    oof[te] = m.predict(pg.loc[te, PERF])
    print("oof", s, f"auc={roc_auc_score(y[te], oof[te]):.3f}", f"{time.time()-t0:.0f}s")
pg["p_oof"] = oof
res["oof_metrics"] = metrics(y, oof)
prem = pg.groupby("player_id").agg(name=("full_name", "first"), gp=("in_headline", "size"), actual=("in_headline", "sum"),
                                   expected=("p_oof", "sum"), first=("season", "min"), last=("season", "max"))
prem["premium"] = prem.actual - prem.expected
prem["ratio"] = prem.actual / prem.expected
prem["z"] = prem.premium / np.sqrt(prem.expected)
elig = prem[(prem.gp >= 300) & (prem.expected >= 10)].copy()
res["premium_top"] = [dict(name=r.name, gp=int(r.gp), actual=int(r.actual), expected=round(float(r.expected), 1), ratio=round(float(r.ratio), 2), z=round(float(r.z), 1))
                      for r in elig.sort_values("z", ascending=False).head(15).itertuples()]
res["premium_bottom"] = [dict(name=r.name, gp=int(r.gp), actual=int(r.actual), expected=round(float(r.expected), 1), ratio=round(float(r.ratio), 2), z=round(float(r.z), 1))
                         for r in elig.sort_values("z").head(10).itertuples()]
res["premium_n_elig"] = int(len(elig))
watch = {660271: "Ohtani", 545361: "Trout", 592450: "Judge", 605141: "Betts", 665742: "Soto", 518692: "Freeman", 673490: "Tatis", 660670: "Acuña", 592518: "Machado", 677951: "Witt", 596059: "Alonso", 547180: "Harper"}
res["premium_watch"] = {}
for pid, nm in watch.items():
    if pid in prem.index:
        r = prem.loc[pid]
        res["premium_watch"][nm] = dict(gp=int(r.gp), actual=int(r.actual), expected=round(float(r.expected), 1), ratio=round(float(r.ratio), 2), z=round(float(r.z), 1),
                                        rank=int((elig.z > r.z).sum() + 1) if pid in elig.index else None)
# 오타니·트라웃 시즌별 프리미엄
res["premium_by_season"] = {}
for pid, nm in ((660271, "Ohtani"), (545361, "Trout"), (592450, "Judge"), (605141, "Betts")):
    d = pg[pg.player_id == pid].groupby("season").agg(gp=("in_headline", "size"), actual=("in_headline", "sum"), expected=("p_oof", "sum"))
    res["premium_by_season"][nm] = [dict(season=int(s), gp=int(r.gp), actual=int(r.actual), expected=round(float(r.expected), 1)) for s, r in d.iterrows()]
print("premium top:", [(x["name"], x["ratio"], x["z"]) for x in res["premium_top"][:8]])
print("watch:", res["premium_watch"])
json.dump(res, open("data/tables/results.json", "w"), ensure_ascii=False, indent=1)
pg[["game_pk", "season", "player_id", "full_name", "team", "in_headline", "p_oof"]].to_csv("data/tables/oof_predictions.csv.gz", index=False)
print("done", f"{time.time()-t0:.0f}s")
