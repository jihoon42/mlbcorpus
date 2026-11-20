"""발표 그래프용 수치: ROC 곡선점, 십분위 보정, 경기별 1순위 적중률, 로지스틱 회귀 표준화 계수.
run_model.py 와 같은 feature 구성 (2019-23 학습 / 2024 early stop / 2025-26 평가)."""
import json, time, warnings
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_curve, roc_auc_score
import lightgbm as lgb

warnings.filterwarnings("ignore")
t0 = time.time()
pg = pd.read_csv("data/tables/player_game.csv.gz")
pg = pg[pg.headline_ambiguous == 0].copy()
pg["run_diff"] = pg.team_runs - pg.opp_runs
pg["wpa_total"] = pg.wpa_bat + pg.wpa_pit
pg["two_way"] = ((pg.pa > 0) & (pg.pitched == 1)).astype(int)
pg["pos_P"] = (pg.position == "P").astype(int)
pg["pos_DH"] = (pg.position == "DH").astype(int)
pg["qs"] = ((pg.outs >= 18) & (pg.p_er <= 3) & (pg.gs == 1)).astype(int)
pg["is_sp"] = (pg.gs == 1).astype(int)
grp = pg.groupby("game_pk")
pg["wpa_rank"] = grp.wpa_total.rank(ascending=False, method="min")
pg["hr_rank"] = grp.hr.rank(ascending=False, method="min")
pg["wpa_gap_to_best"] = grp.wpa_total.transform("max") - pg.wpa_total
pg["game_best_wpa"] = (pg.wpa_rank == 1).astype(int)
pg["game_max_hr"] = grp.hr.transform("max")
pg["date"] = pd.to_datetime(pg.date)
pg = pg.sort_values(["player_id", "date", "game_pk"]).reset_index(drop=True)
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
test = (pg.season >= 2025).values
print("rows", len(pg), f"{time.time()-t0:.0f}s")

def lgb_params():
    return dict(objective="binary", learning_rate=0.05, num_leaves=63, min_child_samples=200,
                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, n_jobs=8)

preds = {}
for name, cols in (("P", PERF), ("PF", PERF + FAME)):
    dtr = lgb.Dataset(pg.loc[fit, cols], y[fit.values])
    dva = lgb.Dataset(pg.loc[valid, cols], y[valid.values])
    m = lgb.train(lgb_params(), dtr, num_boost_round=1500, valid_sets=[dva], callbacks=[lgb.early_stopping(50, verbose=False)])
    preds["lgb_" + name] = m.predict(pg.loc[test, cols], num_iteration=m.best_iteration)
    print(name, m.best_iteration, f"{time.time()-t0:.0f}s")

X = pg[PERF].fillna(0)
pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
pipe.fit(X[train], y[train.values])
preds["lr_P"] = pipe.predict_proba(X[test])[:, 1]
coef = pd.Series(pipe[-1].coef_[0], index=PERF).sort_values(key=abs, ascending=False)
print("LR", f"{time.time()-t0:.0f}s")

yt = y[test]
out = {"n_test": int(test.sum()), "base_rate": float(yt.mean()), "coef_lr_P": [(k, round(float(v), 3)) for k, v in coef.head(12).items()]}

# ROC 곡선: FPR 격자에서의 TPR
grid = np.concatenate([np.linspace(0, 0.1, 21), np.linspace(0.15, 1.0, 18)])
out["roc_grid"] = [round(float(g), 3) for g in grid]
out["roc"] = {}
for k, p in preds.items():
    fpr, tpr, _ = roc_curve(yt, p)
    out["roc"][k] = {"auc": round(float(roc_auc_score(yt, p)), 4), "tpr": [round(float(np.interp(g, fpr, tpr)), 4) for g in grid]}

# 십분위 보정 (예측 확률 순으로 10등분; 상위 구간은 세분)
def calib(p, nb=10):
    order = np.argsort(p)
    bins = np.array_split(order, nb)
    return [{"pred": round(float(p[b].mean()), 4), "actual": round(float(yt[b].mean()), 4), "n": int(len(b))} for b in bins]
out["calib"] = {k: calib(p) for k, p in preds.items()}
# 예측 확률 구간별 (고정 구간)
edges = [0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
out["calib_edges"] = edges
out["calib_binned"] = {}
for k, p in preds.items():
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi) if hi < 1 else (p >= lo)
        rows.append({"lo": lo, "hi": hi, "n": int(m.sum()), "pred": round(float(p[m].mean()), 4) if m.sum() else None,
                     "actual": round(float(yt[m].mean()), 4) if m.sum() else None})
    out["calib_binned"][k] = rows

# 경기별 1순위 적중률: 테스트 경기 중 headline 선수가 1명 이상인 경기에서, 모델이 가장 높게 예측한 선수가 실제 headline 에 들어갔는가
tdf = pg.loc[test, ["game_pk", "in_headline", "wpa_total", "team_won", "hr"]].copy()
for k, p in preds.items():
    tdf[k] = p
tdf["base_wpa_won"] = tdf.wpa_total + 1000 * tdf.team_won     # 이긴 팀 중 WPA 1위
tdf["base_wpa"] = tdf.wpa_total                                 # 전체 WPA 1위
games_with = tdf.groupby("game_pk").in_headline.sum()
gk = games_with[games_with > 0].index
sub = tdf[tdf.game_pk.isin(gk)]
hit = {}
for k in list(preds) + ["base_wpa_won", "base_wpa"]:
    top1 = sub.loc[sub.groupby("game_pk")[k].idxmax()]
    top1_rate = float(top1.in_headline.mean())
    # top-3 안에 headline 선수가 한 명이라도
    ranked = sub.sort_values([ "game_pk", k], ascending=[True, False])
    top3 = ranked.groupby("game_pk").head(3).groupby("game_pk").in_headline.max()
    hit[k] = {"top1": round(top1_rate, 4), "top3": round(float(top3.mean()), 4)}
out["game_top_hit"] = hit
out["n_test_games_with_headline"] = int(len(gk))
out["n_test_games"] = int(tdf.game_pk.nunique())
json.dump(out, open("data/tables/viz_data.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in out.items() if k in ("game_top_hit", "coef_lr_P", "n_test_games_with_headline")}, ensure_ascii=False))
print({k: v["auc"] for k, v in out["roc"].items()}, f"{time.time()-t0:.0f}s")
