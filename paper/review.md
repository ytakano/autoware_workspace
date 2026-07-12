総合評価

査読者の立場で率直に言うと、着想はかなり強く、産業的価値も高いです。特に「実行時間そのもの」ではなく、決定論的なアルゴリズム作業量カウンタを最悪入力探索の目的関数にする点と、Rust移植版を解析用の“計測器”として使う点は、十分に論文化できる新規性があります。

ただし現稿は、タイトルが示す「WCETを境界づけた論文」としてはまだ成立していません。トップクラスのリアルタイム・組込み・システム系会議を想定すると、Major Revision、採否二択なら Reject and Resubmitが妥当です。主な理由は、deployment-tierの近傍数上限、cross-language equal-workの論証、pWCET統計の三つが中核主張を支え切れていないためです。

対象論文: main.pdf⁠￼ main.pdf

観点	評価
新規性	4.5 / 5
産業的意義	4.5 / 5
技術的健全性	2.5 / 5
実験の厳密性	2.0 / 5
記述の明瞭さ	4.0 / 5
再現可能性	1.5 / 5
現稿の総合点	4 / 10
主要問題を修正した場合	7–8 / 10相当

論文の要約と位置づけ

本論文は、AutowareのNDT scan matcherについて、

1. 反復回数、point-leaf評価回数、kd-tree訪問数などから構成される構造的な作業量上限を設ける
2. 決定論的カウンタをfitnessとするhill-climbで最悪入力を探索する
3. Rust側で見つけた入力をC++側に移し、同一入力上で実時間を測る
4. Rust実装のallocation-free、recursion-free、panic-freeという構造的改善を評価する
5. 実走行データで入力契約と移植忠実性を確認する

という三層方式を提案しています。壁時計時間をfitnessにしないため、探索結果を機種非依存にできるという発想は良いです。さらに、実走行リプレイが合成テストでは見つからなかった二つの移植差異を発見した点は、この方法が単なるベンチマーク技巧ではなく、実際の検証価値を持つことを示しています。 main.pdf

特に優れている点

1. 問題設定が実務上まっとう

NDTの実行時間を、平均値ではなく入力依存の最悪ケースとして扱っている点は正しいです。反復回数、近傍数、kd-tree探索量が入力幾何に依存するため、古典的な静的WCET解析だけでは扱いにくい、という導入も説得力があります。 main.pdf

2. カウンタ駆動探索は再利用性のあるアイデア

Niter, Σnbr, Σkdを用いた探索は、測定ノイズやCPU周波数、OS干渉から探索を切り離せます。この方法はNDTに限らず、ICP、経路探索、衝突判定、画像特徴マッチングなど、データ依存ループを持つ産業カーネルに展開可能です。

特に、Σnbr = P · Kmax · (Niter+1)を実際に飽和させた点は、少なくともkernel-evaluation軸では探索が解析上限に到達したことを明確に示しています。 main.pdf

3. 「作業量」と「単位作業当たり時間」を分離したのは良い

論文後半で、作業量上限は構造的に扱い、実時間はプラットフォーム依存の観測値として区別しています。この認識自体は非常に健全です。特にSection VI-Eの「絶対的な時間上限を証明したわけではない」という整理は、論文全体で最も重要な記述の一つです。 main.pdf

4. ヒープ割当の定量化は実務的に価値がある

C++実装でpoint-pass当たり約11回、最悪fixtureで68万回超の割当が発生し、Rust実装では予約済みworkspaceによって0回となる結果は、平均性能だけでなく時間予測可能性の観点で意味があります。

ただし、後述するように「mallocがあるのでWCETは数学的に無限」という表現は強すぎます。「現在のallocator/system modelでは十分に上限を与えにくい構造的ハザード」とするのが正確です。

5. 脅威への自己認識は比較的誠実

powersave governor、warm cache、1台のみ、100 samples、pWCETの統計的不十分さなどを著者自身が明記しています。問題を隠していない点は評価できます。もっとも、現状ではそれらが「将来対応」ではなく、主要主張を成立させるための必須実験になっています。 main.pdf

⸻

主要な問題点

1. Deployment-tierの K \le 8 は、論文自身の結果によって反証されている

これは最重要の技術的問題です。

Section IVでは、voxel centroidはvoxel内の任意位置にあり得るため、search radiusがvoxel sizeと同じなら、堅牢な幾何上限は1軸当たり3セル、合計最大27 leafであると述べています。その一方でdeployment-tierでは、disjoint tileなら「cornerを共有する8 voxel」に限定されるとして、legal-worstを各pointちょうど K=8 で構築し、これをdeployment geometric ceilingとして扱っています。 main.pdf

ところが実データでは、実際に max K = 9 が観測されており、論文自身が「load-bearing boundは8ではなく27」と明記しています。 main.pdf

したがって、

* legal-worstはdeployment-tierの上限入力ではない
* K=8 を根拠にした4.6倍のbound tighteningは、現状では防御可能なWCET boundではない
* 「hardest preprocessing-reachable input we can construct」は、上限証明ではなくstress testにすぎない

ということになります。

必要な修正

deployment-tierは少なくとも K \le 27 を使って再計算すべきです。より小さい上限を主張するなら、map生成処理がcentroid位置をどの範囲に拘束するかを形式的に示す必要があります。

また、実際にboundaryで以下を検査すべきです。

* tileの非重複
* voxel sizeとsearch radiusの結合
* source点数 P
* map leaf数
* centroid配置に関する必要条件
* 予約済みbuffer capacity

「上流が守るはずの契約」ではなく、実行時に検査され、違反時の動作が規定された契約になって初めてdeployment-tier boundが保証になります。

2. C++のengine-tier worst caseは、現状のRust探索では境界づけられていない

Rust実装には K_{\max}=64 のhard capがありますが、C++実装はunbounded neighbor setを収集すると記述されています。さらに論文は、重複tileを増やすとRustは64で打ち切る一方、C++のコストはtile multiplicityとともに増え続けると認めています。 main.pdf

つまり、untrusted-input / engine-API tierについては、

* Rust探索空間は K \le 64
* C++入力空間は K > 64 を許す
* K>64 では両者のアルゴリズム作業量が一致しない

ため、search-00はC++ engine API全体におけるworst inputではありません。

この状態で「Rustで見つけたworst inputがC++にもworst inputとして移る」と一般化するのは不適切です。

必要な修正

次のどちらかが必要です。

1. 入力領域を明示的に
    D=\{x\mid K_{\mathrm{C++}}(x)\le64,\ \text{その他の等価条件を満たす}\}
    と定義し、「domain D 内でのworst」と主張する。
2. C++にも解析上のneighbor boundを導入するか、tile数・重複数をAPI契約として制限し、両実装の入力空間を一致させる。

現状の「untrusted-input tier」という名称は、実際には無制限入力を扱えていないため、特に危険です。

3. 同一反復回数は「equal work」の証明にならない

論文では、C++とRustの iteration_num が一致すれば、equal workがper-inputでcertifyされたとしています。 main.pdf

しかし、同じ反復回数であっても、

* 各pointのneighbor数
* neighborの順序
* kd-tree訪問ノード数
* line-searchの試行数
* 分岐経路
* score-only evaluationの回数

は異なり得ます。したがって、

N_{\mathrm{iter}}^{C++}=N_{\mathrm{iter}}^{Rust}

はequal workの必要条件にはなっても、十分条件ではありません。

さらに実データでは28/22,416 frameの残差があり、論文自身も「bit-exactとはtested domain上での意味」と限定しています。通常の意味でのbit-exactではありません。

必要な修正

解析専用のC++ buildを用意し、少なくとも以下のtrace hashまたはcounterを比較すべきです。

* 各passのneighbor count
* Σnbr
* Σkd
* line-search evaluation count
* neighbor ID列またはそのhash
* transformed-point列のhash
* score/gradient/Hessianのbit patternまたは適切な正規化hash

「production C++ sourceを変更できない」という制約は、製品バイナリを変更できないことと、解析専用forkを作れないことを分けて議論すべきです。解析専用instrumented buildによるtranslation validationが現実的です。

タイトル・abstractでは、bit-exactよりも

work-equivalent on per-input certified traces

のような表現が安全です。

4. 作業量モデルに未整理の項目とoff-by-oneがある

Equation (1)は N_{\mathrm{iter}} 倍として書かれていますが、実験上のkernel-evaluation最大値は N_{\mathrm{iter}}+1=31 passesとして計算されています。

ここでは少なくとも、

* Newton iteration数
* initial derivative pass
* score-only pass
* line-search trial pass
* final evaluation pass

を分離し、Npassを別変数にする必要があります。

特にMore–Thuente line searchは、実装によって複数のtrial evaluationを行います。現在のモデルにすべてのtrialが含まれるのか、最大trial数がどこで静的に制限されるのかが読者には分かりません。ここが抜けている場合、作業量上限そのものが不完全です。

加えて、kd-tree部分は

\Sigma_{\mathrm{kd}}\le P\,N_{\mathrm{pass}}\,N_{\mathrm{leaves}}

というparametric boundにすぎません。Nleavesまたはmap memory capacityがAPI上で制限されていないなら、絶対的なengine-tier boundにはなりません。

推奨する記述形式

前提条件を表にまとめるとよいです。

項目	上限	誰が強制するか	違反時の動作
source点数 P	1500	preprocessing / boundary validator	reject
Newton iterations	30	loop guard	stop
line-search trials	L_{\max}	loop guard	fallback
neighbor数 K	27または64	geometry / hard cap	reject or truncate
map leaves	N_{\max}	map loader	reject
buffer capacity	固定値	preallocation contract	reject、再割当禁止

5. 「proven」「machine-checked」の語が強すぎる

Property-based testingは強力なテスト手法ですが、一般に全入力に対する形式証明ではありません。counting allocatorで0 allocationsを観測したことも、あらゆる経路でのallocation absenceの証明とは異なります。

論文中では、

the work bound is proven — its terms are enforced by construction and machine-checked

と述べていますが、実際の根拠がproperty tests、lint、動的allocator countingであれば、次のように強度を分けるべきです。

* 構文的に強制: 固定上限付きfor/while、固定長配列
* 静的解析で確認: panic可能呼出し、allocation call graph、recursion
* テストで確認: randomized property tests、counting allocator
* 形式証明済み: 実際にproof assistant等で示した場合のみ

また、zero allocationは「予約容量以内」という契約に依存し、容量超過時にはbuffer growthが起こると論文自身が認めています。したがってabstractでは zero allocation under the declared capacity contract と書くべきです。 main.pdf

6. 現在の測定条件ではWCET論文の主要実験として不十分

測定はpowersave governor、container、warm cache、1台、各fixture 100回であり、performance governor、isolated core、cold cache、interference co-runnerはTODOのままです。

これは単なる将来改善事項ではなく、次の主張を支えるために必須です。

* C++とRustの最大遅延比較
* tail特性
* allocator hazard
* 100 ms deadlineに対するmargin
* pWCET

また、C++はGCC -O2、Rustはreleaseとしか書かれておらず、通常Rust releaseは異なる最適化設定になる可能性があります。以下を明示すべきです。

* 全compiler flags
* target-cpu
* LTO
* FMA contraction
* fast-math有無
* OpenMP runtime overhead
* link mode
* allocator
* CPU frequencyとthermal state
* SMT、IRQ affinity、NUMA
* 実験順序のランダム化またはC++/Rustのinterleaving

この論文が比較しているのは「言語」ではなく、PCL/FLANNベースのC++実装と、flat array・custom kd-treeを持つRust実装です。「Rustが速い」ではなく、this Rust implementation is faster than this C++ baselineと限定すべきです。

さらに、bare-metal AArch64が本来のdeployment targetであるのに、target測定がfuture workなのは弱いです。cross-ISA transferを主要貢献に置くなら、少なくともx86_64とAArch64でcounter/trace一致を示す必要があります。

7. pWCET部分は現状では削除または大幅な格下げが必要

Table VIIは100 samplesを10個のblock maximaに分け、わずか n=10 でmoment estimatorのGumbel fitを行い、10^{-9} per-block quantileを外挿しています。これは統計的に非常に不安定です。独立性、定常性、domain-of-attraction、confidence intervalの確認もありません。 main.pdf

さらに内部矛盾があります。

* p.6本文: 「\beta \le 1.3 ms everywhere」
* Table VII: \beta=15.81, 15.41, 12.34 msなど

また、

* C++ search-00: 1201.5/937.4-1 \approx 28\%
* Rust search-00: 868.9/656.0-1 \approx 32\%

なので、「measured maximumよりa few percent上」という本文記述とも一致しません。

この状態では、pWCETをabstractやcontributionに含めるべきではありません。現稿では「exploratory EVT tail fit」程度に留めるのが妥当です。

正式に残すなら、少なくとも以下が必要です。

* 1,000–10,000以上のsamples
* 複数日・複数run
* randomized/interference-aware measurement protocol
* GEVまたはPOT/GPD
* shape parameterの推定
* independence / stationarity diagnostics
* confidence bands
* threshold/block-size sensitivity
* per-block確率からper-align確率への変換
* fit外挿距離の明示

8. 結果数値が複数箇所で一致していない

union-worstについて、

* p.4本文: 876 ms → 608 ms
* Table II: 937.4 ms → 656.0 ms
* Table Vの P=2000: 891.2 ms → 608.6 ms

となっています。

異なるrunや実験系列なら、そのことを明記し、本文は対応する表の値を引用すべきです。現状は、複数世代の実験結果が原稿内に混在しているように見えます。

各表に次の情報を付けるとよいでしょう。

* run ID
* git commit
* fixture hash
* binary hash
* measurement date
* CPU設定
* sample count
* raw-data artifactへの参照

9. 探索が「時間最悪」を見つける保証はない

探索目的はlexicographicな (N_{\mathrm{iter}},\Sigma_{\mathrm{nbr}},\Sigma_{\mathrm{kd}}) です。これは再現可能ですが、時間コストは一般に重み付き和であり、例えば反復回数が1少なくてもkd訪問数やcache missが大きい入力の方が遅い可能性があります。

より自然なのは、プラットフォーム非依存性を維持したまま、カウンタ空間のPareto frontierを保存し、その全候補を各プラットフォームで測る方法です。

加えて、以下のablationが必要です。

* hill-climb対random search
* counter fitness対wall-clock fitness
* hand-built fixturesのみ対search追加
* 単一seed対複数seed
* saturationまでの評価回数・時間
* mutation operatorごとの寄与
* lexicographic対Pareto search

kd-tree traversal項について解析最大値に到達していないことを著者自身が認めているため、「worst-input search」という名称は「high-cost input search」程度に弱めるか、入力空間を明示的に限定すべきです。 main.pdf

10. 実走行検証の実質的なサンプル数を明確にすべき

Table VIでは22,416 framesを収集したとしていますが、Niter、kd nodes、timingなどは501 on-map framesについてのみ報告されています。これは全体の約2.2%です。 main.pdf

したがって、次を報告すべきです。

* なぜ21,915 framesがoff-mapなのか
* off-map判定条件
* 28 divergence framesのうち何件がon-mapか
* equal-work率をon-map subsetで計算するとどうなるか
* 501 framesが連続区間か、散在区間か
* production filterの実際のpriorを使った場合の結果
* nominal、initialization、dropoutの各scenario別集計

もし28件の差異が主に501 on-map framesに集中しているなら、「0.12% residual」は実質的な処理フレームに対してはかなり大きな割合になる可能性があります。

また、一経路・一車両・degraded-prior trackは有用なcase studyですが、「contracts and marginsをvalidateした」ではなく、one-drive evidence consistent with the contracts程度が妥当です。

11. Unit-cost regressionの根拠が弱い

Table IVは n=6 に対して説明変数2個とinterceptを推定しており、自由度はごく小さいです。高い R^2 だけでは、単位コストの妥当性や因果的な帰属は示せません。しかも説明変数同士が相関している可能性があり、Rustのinterceptは負です。 main.pdf

必要なのは、

* coefficient confidence intervals
* residual plots
* collinearity診断
* leave-one-fixture-out validation
* held-out fixturesによる予測誤差
* hardware counters
* kernel-only / kd-only microbenchmarks
* compiler生成コードの比較

です。

「pointer indirectionやPCL/FLANN machineryが原因」という説明は、現状では妥当な仮説ですが、論文自身が認めるようにcounter-provenではありません。

⸻

再投稿までの優先修正案

最優先

1. Deployment-tierの幾何上限を27で再構築する
    legal-worstをboundではなくwitness/stress fixtureとして再定義し、4.6倍の主張を再計算する。
2. equal-work certificateを強化する
    iteration countだけでなく、Σnbr、Σkd、line-search数、neighbor trace hashを両実装で比較する。
3. 入力領域を形式的に定義する
    Rust cap 64とC++ uncappedの差を解消し、「どの入力集合に対するboundか」を明記する。
4. 作業量式を書き直す
    NiterとNpassを分離し、初期pass、line search、map leaf上限、capacity前提を含める。
5. 測定をやり直す
    performance governor、core isolation、cold/warm cache、interference、複数run、target AArch64を含める。
6. pWCETを再構築するか削除する
    現在の n=10 Gumbel結果を主要貢献に置くのは避ける。
7. 全数値を一つのartifact manifestから生成する
    表・本文・abstract間の不一致をなくす。

次点

* exact Autoware/Rust commitを記載
* generator、seed、search budget、fixture binaries、raw timingを公開
* Pareto searchとablationを追加
* nominal-prior実走行と複数routeを追加
* C++とRustのcompiler条件を揃える
* boundary validatorを実装し、そのオーバーヘッドを測定
* analysis対象がalign kernelのみであり、map build、preprocessing、ROS schedulingは含まないことをタイトルとabstractで明確化

⸻

記述・構成面

文章の流れは全体として良く、Table I–VIも比較的読みやすいです。p.6のFigure 1も視認性は高いです。ただし、現在のPDFには以下の赤いTODOが残っています。

* 著者メール・共著者・所属
* exact commits
* performance governor、cold-cache、co-runner再測定
* 1,000+ samples、POT/MLE、CI

この状態では投稿原稿として未完成です。

タイトルも現状では少し強すぎます。Section VI-Eで「absolute time boundではない」と明言しているため、例えば次の方が内容に合っています。

Counter-Guided Work Bounding and Cross-Language Timing Characterization of an Industrial NDT Scan Matcher

あるいは、

Toward WCET Analysis of an Industrial NDT Scan Matcher: Deterministic Cost Search and Cross-Language Validation

abstractでは、次の区別を冒頭で明言すると論文がかなり締まります。

We establish a parametric bound on algorithmic work and empirically characterize the time per unit of work; we do not claim a certified hard time bound on the evaluated x86 platform.

最終判定

現稿: Reject and Resubmit / Major Revision

ただし、これはテーマやアイデアが弱いからではありません。むしろ、核となるアイデアはかなり良く、産業システムのWCET研究として面白いです。現在は「強い方法論を持つ有望な実験報告」までは到達していますが、「NDT matcherのWCETを境界づけた」という中心命題には、まだ論理と実験の隙間があります。

特に、

1. K=8 と K=27 の矛盾を解消する
2. equal iterationをequal workと呼ばない
3. Rust capとC++ uncappedの入力空間差を処理する
4. pWCETを統計的に作り直す
5. target条件で測定する

の五点が直れば、再投稿時にはかなり競争力のある論文になります。
