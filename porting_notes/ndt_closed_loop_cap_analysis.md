# Closed-loop replay における C++/Rust 比較 — 反復上限(cap)分析

対象実験: NDT+EKF+GNSS closed-loop stack replay(GNSS 再初期化つき、2026-07-25/26 実施)。
İstanbul 57 分 bag(34,375 clouds @10 Hz)、タイルマップ(500 m extent / 150 m 差分ロード)、
CFS・4 worker(OpenMP / Rayon)、performance governor 3.2 GHz、共有固定初期姿勢、
watchdog(starvation 25 s、TPE レイテンシの twist 前方予測補償)。run 順 cpp1→rust1→rust2→cpp2。

- 凍結データ: `paper/data/stack_replay.json`(生データ: `stack_replay_results_reinit/`)
- エンジン: fork `ndt_in_rust_3_clean` @ `8fc5f0ab`
- 論文該当節: `paper/sections/05-evaluation.tex` の "Closed-loop stack replay with GNSS recovery"

## 1. cap 率とは

NDT の Newton 反復ループの停止条件は

```
iter >= max_iterations(30)  または  ステップ長 a_t < trans_epsilon(0.01)
```

であり(shipped 設定: step_size=0.1、ε=0.01 — capture の `params.bin` 実測で検証済み)、
**cap 率 = `iteration_num >= 30` のフレーム割合**。分母は closed-loop では aligned frames
(`iteration_num > 0`、map 未ロード等の 0 反復行を除外)。

実測(aligned frames 分母):

| run | aligned | cap 数 | **cap 率** | 反復中央値 |
|---|---|---|---|---|
| cpp1 | 32,152 | 8,938 | **27.8%** | 15 |
| cpp2 | 31,501 | 7,460 | **23.7%** | 15 |
| rust1 | 33,658 | 3,474 | **10.3%** | 13 |
| rust2 | 33,003 | 3,485 | **10.6%** | 14 |

repeat 帯(同一エンジン 2 run)はタイト、言語帯は非重複 — カオスばらつきではなく系統差。

## 2. cap に到達しやすい条件

1. **prior 誤差が補正予算を超える**: 1 反復の更新は step_size=0.1 で頭打ちのため、
   30 反復の総補正 ≈ 3 m。prior 誤差 ≫ 3 m では原理的に到達不能(open-loop の
   degraded track、prior 誤差中央値 156 m → cap 73.1% が実証)。
2. **最適解近傍での振動**: 良好 prior でも Newton ステップが ε=0.01 未満に落ちず
   30 回使い切る(shipped-osc fixture が合成系での証人。実データでは §3)。
3. **幾何・マップ構造の縮退**: トンネル回廊(進行方向拘束なし)、マップ境界の
   部分オーバーラップ、マップ表現(同一走行で crop 単一タイル 44–73% vs
   動的タイル 10–28%)。
4. **パラメータ**: ε を絞る(geom-stress は非 shipped ε=1e-10 で強制 30 反復)、
   step_size を絞る。

点数 P・近傍数 K は反復あたりコストを変えるだけで反復回数には効かない。

## 3. 実データでの「最適解近傍の振動」とその内訳

cap 到達フレームを、ノード自身の品質スコア NVTL(最近傍ボクセル変換尤度、
採択閾値 2.3)で分解:

| run | cap 総数 | NVTL ≥ 2.3(採択水準の姿勢に到達済み) | NVTL < 2.3(真に迷子) | cap フレーム NVTL 中央値 |
|---|---|---|---|---|
| cpp1 | 8,938 | **5,928(66%)** | 3,010 | 2.45 |
| rust1 | 3,474 | **2,459(71%)** | 1,015 | 2.51 |

**cap の約 2/3〜7 割は「スコア上は良い解に居るのに ε 収束条件を満たせない」振動型**。
EKF prior は数 m 級で良解到達には数反復で足りるため、残りは近傍振動に消費されている。
すなわち振動型 cap は正常運転・良好 prior 下でも起きる = 「収束失敗」ではなく
「収束判定を満たせないまま最大仕事量を消費する」ケース。WCET を I_max=30 前提で
見積もるべき最も強い実データ根拠。

## 4. 振動検出(救済条項)はほとんど機能していない

upstream(autoware_core main と同一。merge-base `e23e6b0d` に対し本 branch の
当該ロジック差分 0 行)の採択判定は
`ndt_scan_matcher_core.cpp:561`:

```cpp
is_succeed_scan_matching =
    (is_ok_iteration_num || is_local_optimal_solution_oscillation) && is_ok_score;
```

つまり設計上は「cap でも振動検出(往復カウント `oscillation_num > 10`)かつスコア良好なら
採択」という救済条項がある。しかし実測では:

- cpp1 の published(accepted)数 22,686 vs "OK" メッセージ数 22,662 — **差 24 フレームのみ**
- 一方で良スコア cap は 5,928 フレーム存在

→ **救済条項の発火は cap の 0.4% 未満**。単純往復カウント(閾値 10)は実走行の
振動パターン(NVTL ≥ 2.3 の振動型 cap)をほぼ検出できず、良い姿勢が iteration-limit を
理由に棄却され続けている。検出器の感度改善は C++ の coverage 差(§5)の一部を
回復し得る改善提案として成立する。

## 5. なぜ Rust の方が cap 到達率が低いか

**エンジンの数学は同一**(同一入力で反復回数はビット一致。open-loop 22,416 フレーム中
22,283 一致、乖離 133 件は数値感度由来で cap 率差なし)。差は閉ループの動力学から生じる:

```
Rust: align 中央値 7.6–8.0 ms          C++: align 中央値 17.5–17.9 ms(p99 ~45 ms)
  → 10 Hz 内に余裕                       → 処理中の cloud 取りこぼし増
  → 処理 33.0–33.7k フレーム             → 31.5–32.2k フレーム
  → EKF 補正が高頻度・低遅延             → prior がわずかに古い/粗い
  → 少ない反復で ε 収束圏                → 収束圏の縁から始まるフレーム増
    (非 cap 中央値 13–14)                 (中央値 15)
```

さらに upstream の「cap → 棄却」(§4)が**正帰還**を作る:
cap → 棄却 → EKF は twist 外挿のみ → 次 prior 劣化 → さらに cap。
C++ はベース遅延が大きいためこのスパイラルに入りやすく抜けにくい
(cap フレーム自体が 30 反復 ≈ 45 ms で取りこぼしも増える)。

結果(システムレベル指標):

| 指標 | C++(2 run) | Rust(2 run) |
|---|---|---|
| accepted-output coverage | 82.3–83.2% | 93.5–96.5% |
| GNSS 再初期化(全 26 回成功) | 7–11 回 | 3–5 回 |
| starvation 区間 | 共通 2 区間 + **C++ のみ 2 区間** | 共通 2 区間のみ |
| 100 ms 超過 | 3–4 フレーム/run(全て回復窓内の TPE 競合) | 0 |
| align max | 141.5 / 155.9 ms | 25.8 / 23.8 ms |

要約: **同じアルゴリズムを ~2.2 倍速く回すことで prior が新鮮に保たれ、
cap→棄却→prior 劣化の正帰還に入りにくい**。エンジンの速度差がシステムレベルの
頑健性(coverage・回復回数)に伝播する、が閉ループ実験の中心的知見。

## 6. 付録: GNSS 再初期化 watchdog の設計(`bench/l1b_reinit_watchdog.py`)

素の stack replay は「初期化 1 回・復帰経路なし」で、喪失後は二度と戻れない
(旧実験は最長 2,088 秒の喪失を放置)。watchdog は production の GNSS 再初期化を
replay に再現する装置だが、production の再初期化は**停車中**が前提
(`pose_initializer` の stop_check)であり、記録済み走行は止められない。
そのための適応が以下の 2 点。

### トリガ: starvation 25 秒のみ

- **accepted NDT pose(EKF 採択ゲート通過出力)が 25 秒途絶**したときだけ発火。
  値の根拠はベースライン run の実測: 自己回復する良性ギャップは最大 19.2 秒
  (その間 twist デッドレコニングが ~3 m 精度を維持)、本物の喪失は 54〜2,088 秒。
- **EKF−GNSS 乖離トリガは検討の末に撤廃**(v1 で実装→失敗)。トンネル区間では
  GNSS-INS 側が ~420 m ドリフトし NDT は健全なため、乖離トリガは健全なループを
  リセットしてしまう。原則「NDT が出力しているなら NDT を信じる」。

### TPE レイテンシの twist 前方予測補償

再初期化の実体は pose_initializer AUTO と同一の呼び出し列:
GNSS-INS シード → `ndt_align_srv`(TPE = Tree-structured Parzen Estimator による
多点初期姿勢探索 align、**3〜6 秒**かかる)→ `/initialpose3d` → trigger 再有効化。

問題は、align 実行中も bag が再生され続け、車両が数十〜100 m 進むこと。
refined pose を `stamp=now` で注入すると「数十 m 古い姿勢を現在値として EKF に
教える」ことになる。**v1 の実測**: 補償なし注入で、健全だったループ
(EKF−GNSS 乖離 1.2 m)が 50〜80 m の持続振動に陥った(注入 → EKF 破壊 →
再発散 → 再注入の自己維持ループ)。production はこれを停車で回避しており、
init スクリプト(`l1b_ndt_align_init.py`)が bag を pause するのも同じ理由。

**v2 の解決**: align 要求時刻から発行時刻までの live twist(並進・角速度)を
バッファし、平面デッドレコニングで refined pose を前進させてから注入する:

```
yaw += wz·dt;  x += vx·cos(yaw)·dt;  y += vx·sin(yaw)·dt
```

実証値: 本番 run で 104 m / 127 m の移動分を補償し、注入直後の EKF−GNSS 乖離は
2.9 m / 2.7 m(`reinit_events.csv` の `predict_m` 列に記録)。

### 安全弁

| 機構 | 役割 |
|---|---|
| align の success フラグ | 実効的な妥当性ゲート。トンネル内で GNSS シードが数百 m ズレていれば align が失敗し、誤注入を防ぐ(GNSS 共分散は tunnel でも ~mm 級を報告するため cov ゲートは不可) |
| クールダウン 30 秒 / リトライ 10 秒 | 再ロック中の連続介入・TPE 乱発を防止 |
| GNSS 鮮度 1 秒 | 古い GNSS シードでの注入を防止 |
| arm 条件 | 最初の accepted pose まで発火しない(初期化は共有 fixture 担当) |
| `reinit_events.csv` | 全判定・シード・成否・補償距離を記録(100 ms 超過が全て回復窓内であることの証明にも使用) |

production との残る逸脱は「停車 → twist 前方予測」の置換 1 点と、
「いつ再初期化するか」の自動化(production では operator/MRM の領分)。
検証: 30 分 run で誤発火ゼロ、本番 4 run で 26/26 発火が全て正当・全て成功。

## 限定条件

- ルートは意図的に LiDAR 困難(海底トンネル・長大橋・都市峡谷)— 全数値はストレスルート値
- エンジンあたり 2 run、ground truth なし、閉ループのカオス性により run レベル比較のみ
- watchdog は production の停車前提を twist 前方予測で代替(starvation 25 s は
  ベースライン run の良性ギャップ最大 19.2 s に基づき選定・全 run 固定)
