#!/usr/bin/env python3
"""경기 x 출전 선수 테이블 생성 (headline 예측 모델용).

입력: data/raw/games/{season}/{pk}/{feed,winprob,content.en}.json.gz, data/raw/manifest.sqlite
출력: data/tables/player_game.<tag>.csv (선수 행), data/tables/games.<tag>.csv (경기 행), data/tables/done.<tag> (체크포인트)

사용: python3 analysis/build_player_game.py --root . --seasons 2019,2020 --tag a --budget 165
같은 tag 로 다시 실행하면 done 파일 기준으로 이어서 돈다.
"""
import argparse, csv, gzip, html, json, os, re, sqlite3, sys, time

TAG_RE = re.compile(r'<(script|iframe|style)[^>]*>.*?</\1>', re.S | re.I)
TAGS_RE = re.compile(r'<[^>]+>')

PLAYER_COLS = [
    'game_pk', 'season', 'date', 'team_id', 'team', 'opp', 'is_home', 'team_runs', 'opp_runs', 'team_won',
    'player_id', 'full_name', 'last_name', 'position', 'bat_order', 'is_starter_bat',
    'pa', 'ab', 'h', 'd2', 'd3', 'hr', 'rbi', 'r', 'bb', 'so', 'sb', 'tb',
    'pitched', 'gs', 'outs', 'bf', 'p_k', 'p_bb', 'p_h', 'p_hr', 'p_er', 'p_r', 'pitches',
    'win', 'loss', 'save', 'hold',
    'wpa_bat', 'wpa_pit', 'n_pa_bat', 'n_pa_pit', 'max_li',
    'in_headline', 'headline_ambiguous', 'n_body',
]
GAME_COLS = ['game_pk', 'season', 'date', 'home', 'away', 'home_runs', 'away_runs', 'headline', 'body_chars', 'n_players_in_headline']


def clean(b):
    return html.unescape(TAGS_RE.sub(' ', TAG_RE.sub(' ', b or '')))


def name_re(name):
    return re.compile(r'(?<!\w)' + re.escape(name) + r'(?!\w)')


def ip_to_outs(ip):
    try:
        a, b = str(ip).split('.')
        return int(a) * 3 + int(b)
    except Exception:
        return 0


def gi(d, k):
    v = d.get(k, 0) if d else 0
    try:
        return int(v)
    except Exception:
        return 0


def process_game(root, season, pk):
    base = f"{root}/data/raw/games/{season}/{pk}"
    feed = json.load(gzip.open(f"{base}/feed.json.gz", 'rt', encoding='utf8'))
    wp = json.load(gzip.open(f"{base}/winprob.json.gz", 'rt', encoding='utf8'))
    ct = json.load(gzip.open(f"{base}/content.en.json.gz", 'rt', encoding='utf8'))
    rec = ((ct.get('editorial') or {}).get('recap') or {}).get('mlb') or {}
    headline = rec.get('headline') or ''
    body = clean(rec.get('body') or '')
    if not headline and not body:
        return None, None
    gd = feed['gameData']
    ld = feed['liveData']
    date = gd['datetime'].get('officialDate', '')
    teams = {side: gd['teams'][side] for side in ('home', 'away')}
    runs = {side: gi(ld['linescore']['teams'].get(side), 'runs') for side in ('home', 'away')}
    people = gd.get('players', {})
    dec = ld.get('decisions') or {}
    dec_ids = {k: (dec.get(k) or {}).get('id') for k in ('winner', 'loser', 'save')}

    # WPA per player from winProbability plays
    wpa_bat, wpa_pit, n_bat, n_pit, max_li = {}, {}, {}, {}, {}
    plays = wp if isinstance(wp, list) else (wp.get('allPlays') or [])
    for pl in plays:
        try:
            w = pl.get('homeTeamWinProbabilityAdded')
            if w is None:
                continue
            w = float(w)
            top = bool((pl.get('about') or {}).get('isTopInning'))
            wb = -w if top else w  # 타자 팀 기준
            m = pl.get('matchup') or {}
            b = (m.get('batter') or {}).get('id')
            p = (m.get('pitcher') or {}).get('id')
            li = pl.get('leverageIndex')
            li = float(li) if li is not None else 0.0
            if b:
                wpa_bat[b] = wpa_bat.get(b, 0.0) + wb
                n_bat[b] = n_bat.get(b, 0) + 1
                max_li[b] = max(max_li.get(b, 0.0), li)
            if p:
                wpa_pit[p] = wpa_pit.get(p, 0.0) - wb
                n_pit[p] = n_pit.get(p, 0) + 1
                max_li[p] = max(max_li.get(p, 0.0), li)
        except Exception:
            continue

    rows = []
    # 같은 성이 두 명 이상 출전한 경기의 headline 매칭은 모호 표시
    played = []  # (side, pid, bp)
    for side in ('home', 'away'):
        for key, bp in (ld['boxscore']['teams'][side].get('players') or {}).items():
            st = bp.get('stats') or {}
            bat = st.get('batting') or {}
            pit = st.get('pitching') or {}
            has_order = 'battingOrder' in bp
            if not (has_order or gi(pit, 'battersFaced') > 0 or gi(bat, 'plateAppearances') > 0 or ip_to_outs(pit.get('inningsPitched', 0)) > 0):
                continue
            pid = (bp.get('person') or {}).get('id')
            if not pid:
                continue
            played.append((side, pid, bp, bat, pit, has_order))
    last_counts = {}
    for side, pid, bp, bat, pit, has_order in played:
        ln = (people.get(f"ID{pid}") or {}).get('lastName') or (bp.get('person') or {}).get('fullName', '').split(' ')[-1]
        last_counts[ln] = last_counts.get(ln, 0) + 1
    n_head = 0
    for side, pid, bp, bat, pit, has_order in played:
        person = people.get(f"ID{pid}") or {}
        full = person.get('fullName') or (bp.get('person') or {}).get('fullName', '')
        ln = person.get('lastName') or full.split(' ')[-1]
        if not ln:
            continue
        rx = name_re(ln)
        in_head = 1 if rx.search(headline) else 0
        amb = 0
        if in_head and last_counts.get(ln, 1) > 1:
            # 전체 이름으로 풀리면 그 선수에게만
            if full and name_re(full).search(headline):
                amb = 0
            else:
                amb = 1
        n_body = len(rx.findall(body))
        n_head += in_head
        opp = 'away' if side == 'home' else 'home'
        order = bp.get('battingOrder')
        try:
            order_i = int(order)
        except Exception:
            order_i = ''
        rows.append([
            pk, season, date, teams[side]['id'], teams[side].get('abbreviation', ''), teams[opp].get('abbreviation', ''),
            1 if side == 'home' else 0, runs[side], runs[opp], 1 if runs[side] > runs[opp] else 0,
            pid, full, ln, ((bp.get('position') or {}).get('abbreviation') or ''), order_i,
            1 if (order_i != '' and order_i % 100 == 0) else 0,
            gi(bat, 'plateAppearances'), gi(bat, 'atBats'), gi(bat, 'hits'), gi(bat, 'doubles'), gi(bat, 'triples'), gi(bat, 'homeRuns'),
            gi(bat, 'rbi'), gi(bat, 'runs'), gi(bat, 'baseOnBalls'), gi(bat, 'strikeOuts'), gi(bat, 'stolenBases'), gi(bat, 'totalBases'),
            1 if (gi(pit, 'battersFaced') > 0 or ip_to_outs(pit.get('inningsPitched', 0)) > 0) else 0,
            gi(pit, 'gamesStarted'), ip_to_outs(pit.get('inningsPitched', 0)), gi(pit, 'battersFaced'), gi(pit, 'strikeOuts'),
            gi(pit, 'baseOnBalls'), gi(pit, 'hits'), gi(pit, 'homeRuns'), gi(pit, 'earnedRuns'), gi(pit, 'runs'),
            gi(pit, 'pitchesThrown') or gi(pit, 'numberOfPitches'),
            1 if dec_ids.get('winner') == pid else 0, 1 if dec_ids.get('loser') == pid else 0, 1 if dec_ids.get('save') == pid else 0,
            gi(pit, 'holds'),
            round(wpa_bat.get(pid, 0.0), 3), round(wpa_pit.get(pid, 0.0), 3), n_bat.get(pid, 0), n_pit.get(pid, 0), round(max_li.get(pid, 0.0), 2),
            in_head, amb, n_body,
        ])
    game_row = [pk, season, date, teams['home'].get('abbreviation', ''), teams['away'].get('abbreviation', ''), runs['home'], runs['away'],
                headline, len(body), n_head]
    return rows, game_row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--seasons', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--budget', type=float, default=165)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    root = a.root
    seasons = [int(s) for s in a.seasons.split(',')]
    tdir = f"{root}/data/tables"
    os.makedirs(tdir, exist_ok=True)
    done_path = f"{tdir}/done.{a.tag}"
    pg_path = f"{tdir}/player_game.{a.tag}.csv"
    g_path = f"{tdir}/games.{a.tag}.csv"
    err_path = f"{tdir}/errors.{a.tag}.log"
    done = set()
    if os.path.exists(done_path):
        done = {int(x) for x in open(done_path).read().split() if x.strip()}
    con = sqlite3.connect(f"file:{root}/data/raw/manifest.sqlite?mode=ro", uri=True)
    q = f"SELECT game_pk, season FROM games WHERE finished=1 AND game_type='R' AND season IN ({','.join('?' * len(seasons))}) ORDER BY season, official_date, game_pk"
    todo = [(pk, s) for pk, s in con.execute(q, seasons).fetchall() if pk not in done]
    total = len(todo) + len(done)
    new_pg = not os.path.exists(pg_path)
    new_g = not os.path.exists(g_path)
    t0 = time.time()
    n = 0
    with open(pg_path, 'a', newline='', encoding='utf8') as fpg, open(g_path, 'a', newline='', encoding='utf8') as fg, \
            open(done_path, 'a') as fd, open(err_path, 'a') as fe:
        wpg, wg = csv.writer(fpg), csv.writer(fg)
        if new_pg:
            wpg.writerow(PLAYER_COLS)
        if new_g:
            wg.writerow(GAME_COLS)
        for pk, s in todo:
            if time.time() - t0 > a.budget or (a.limit and n >= a.limit):
                break
            try:
                rows, grow = process_game(root, s, pk)
                if rows:
                    wpg.writerows(rows)
                    wg.writerow(grow)
            except Exception as e:
                fe.write(f"{s} {pk} {type(e).__name__}: {e}\n")
            fd.write(f"{pk}\n")
            n += 1
        fpg.flush(); fg.flush(); fd.flush()
    print(f"[{a.tag}] processed {n} games in {time.time() - t0:.0f}s; done {len(done) + n}/{total}; remaining {total - len(done) - n}")


if __name__ == '__main__':
    main()
