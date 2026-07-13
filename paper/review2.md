対象: [改訂稿 PDF](sandbox:/mnt/data/main%282%29.pdf)

## 総合評価

かなり良くなっています。前稿への対応は表面的な言い換えではなく、入力領域の定義、測定プロトコル、Pareto探索、実データの分母、EVT診断、AArch64実機評価まで含む実質的な改訂です。特に、タイトルを **“Toward WCET Analysis”** に変更し、align kernelだけが対象で、評価プラットフォーム上のhard WCETは主張しないとabstractで明記したのは適切です。

ただし、トップクラスのリアルタイムシステム系main trackを想定すると、現時点の判定はまだ **Weak Reject / Major Revision** です。理由は一つの中核論証、すなわち

> Rust側のカウンタで極端な入力を見つけ、その作業量がC++側にも同一に移る

というcross-language transferが、現在のcertificateでは十分に証明されていないためです。

| 観点            |           評価 |
| ------------- | -----------: |
| 新規性           |      4.5 / 5 |
| 産業的意義         |      5.0 / 5 |
| 実験設計          |      4.0 / 5 |
| 技術的健全性        |      3.0 / 5 |
| 主張の適切さ        |      3.5 / 5 |
| 再現可能性         |      3.5 / 5 |
| 現稿の総合点        | **6.5 / 10** |
| 以下の主要点を修正した場合 | **8 / 10前後** |

前稿で指摘した問題のうち、(K=8) と (K=27) の混同、line-searchを含むpass数、過剰なpWCET主張、実データ22,416件という分母の扱い、isolated/production-like測定の分離は、ほぼ解消されています。一方、equal-workの証明はまだ部分的です。

---

# 特に改善された点

## 1. Deployment-tierの (K) の扱いは正しくなった

改訂稿は、(K=8) をvoxel-center heuristicによる構成可能なwitness、(K\le27) を一般的な幾何上限として明確に分離しています。`legal-worst`も「tier全体の上限を達成する入力」ではなく、構成されたlower-bound witnessとして扱われています。

さらに、測定上の4.9倍という差と、契約だけから保証されるkernel項の (64/27\simeq2.4) 倍を分けた点もよいです。前稿で最も大きかった論理的問題は、ここでは解消されています。

## 2. (N_{\mathrm{pass}}=N_{\mathrm{iter}}+1) の条件が明示された

初期derivative pass、Newton iteration、More–Thuente refinementの追加passが整理され、production configurationではline searchが無効なので (N_{\mathrm{pass}}=N_{\mathrm{iter}}+1) と説明されています。Table XIIでline-search flag違反時の挙動も明記されており、前稿のoff-by-one問題はおおむね解消しました。

## 3. 測定プロトコルは大幅に強くなった

Profile Bでは、

* isolated pinned core
* SMT sibling offline
* IRQ affinity制御
* 3.2 GHz固定
* 複数sessionとreboot
* fixture/engine順序のランダム化
* cold-cacheとco-runnerの分離
* calibration guard

が導入されています。さらに、Profile Aとのbridge experimentも追加されました。単に「隔離環境の数字」をproductionへ外挿するのではなく、両環境の差を実測した点は非常に良いです。

## 4. EVTの扱いが科学的になった

前稿のGumbel外挿を撤回し、POT/GPD、MLE、bootstrap、threshold sweep、autocorrelation診断を実施したうえで、独立性が成立しないため**外挿確率を主張しない**と結論しています。

これは弱点ではなく、むしろ強みです。見栄えのよい (10^{-9}) quantileを無理に残さず、診断結果に従って棄却した判断は適切です。

## 5. 実データの実質的な分母を正直に示した

22,416 framesのうち、意味のあるmatching workを行うon-map frameは501件であり、28件のdivergenceはすべてその中に存在するため、実質的なequal-iteration率は94.4%である、と明記されています。前稿の0.12%という見せ方だけに依存しなくなったのは重要な改善です。

## 6. Pareto frontierとAArch64評価が追加された

lexicographic fitnessが時間順序を保存しないことを認め、counter Pareto frontier全体を測定した結果、Rustではkd-heavy candidateが`search-00`を1.1%上回ったと報告しています。これは方法の限界を隠さず、実測で確認した良い実験です。

また、Raspberry Pi 4のbare-metal環境で8 fixtureすべてのcounter一致を確認したことも、cross-ISA legの実証として価値があります。

---

# 主要な問題点

## 1. 「bit-exact over (D)」と実験結果が矛盾している

これは依然として最重要の問題です。

Section III-Cでは、bounded-neighbor domain (D) 上でRustとC++がbit-exactであり、iteration count、neighbor set、workが一致すると主張しています。また、equal `iteration_num`を(D)へのmembership checkとして使っています。

しかし、実データではon-map 501件中28件、すなわち5.6%でiteration count自体が異なります。論文はこれをlibm、eigensolver、浮動小数点trajectoryの差として説明しています。つまり、bounded-neighborであることは、数値trajectoryや作業量の一致を保証していません。

形式的には、現在の論文は次の含意を仮定しています。

[
x\in D_K
\Longrightarrow
\mathrm{trace}*{C++}(x)=\mathrm{trace}*{Rust}(x)
]

ここで (D_K) は「どのqueryも64近傍以下」という領域です。しかし、実データの28件がこの含意への反例です。(D_K) はtruncationを排除する領域ではあっても、numerical equivalenceを保証する領域ではありません。

さらに、

[
N_{\mathrm{iter}}^{C++}=N_{\mathrm{iter}}^{Rust}
]

から、

[
\Sigma_{\mathrm{nbr}}^{C++}=\Sigma_{\mathrm{nbr}}^{Rust},
\qquad
\Sigma_{\mathrm{kd}}^{C++}=\Sigma_{\mathrm{kd}}^{Rust}
]

は導けません。truncationやneighbor差があっても、偶然同じiteration countで収束する可能性があります。したがってequal iterationは、

* (D) membershipの十分条件ではない
* equal neighbor workの十分条件ではない
* equal kd traversalの十分条件ではない

という問題があります。

### 必要な修正

入力領域を少なくとも二つに分けるべきです。

[
D_K=
{x\mid \max_q K_{\mathrm{uncapped}}(q)\le64}
]

[
E_{\mathrm{trace}}=
{x\in D_K\mid
H_{\mathrm{C++}}(x)=H_{\mathrm{Rust}}(x)}
]

ここで (H) はper-input trace hashです。cross-language transferは (D_K) 全体ではなく、**certificateが通った (E_{\mathrm{trace}}) に限って主張**します。

解析用C++ buildを作り、少なくとも以下を比較してください。

* derivative-pass count
* 各passのpoint count
* 各queryのneighbor count
* (\Sigma_{\mathrm{nbr}})
* neighbor leaf IDと順序のhash
* line-search evaluation count
* score、gradient、HessianのhashまたはULP差
* 可能なら各実装固有のkd-tree node visits

production C++ sourceを変更できない制約は、製品バイナリを変更しない理由にはなりますが、解析用instrumented buildを作らない理由にはなりません。論文自身も解析buildが可能だと認めているため、ここは実施すべきです。

また、`bit-exact`という語は現状では使わない方がよいです。fixture上でもfinal poseは最大 (2\times10^{-7}) m差、scoreは最大1 ULP差であり、bit-exactではありません。次の表現が安全です。

> a high-fidelity Rust port with per-input trace-equivalence certification

または、

> work-equivalent on individually certified inputs

## 2. C++側の (\Sigma_{\mathrm{kd}}) が測られていない

C++はPCL/FLANN由来のsearch machineryを用い、Rustは独自のflat-array kd queryを用いています。neighbor setが同じでも、両実装が訪問するkd-tree node数が同じとは限りません。

そのため、Rust側の (\Sigma_{\mathrm{kd}}) をC++側にも「shared counter」として使い、Table VIの係数を`ns/kd node`と解釈するのは、現状では正当化できません。これは実際には、

> ns per Rust-reference kd-node count

または、

> geometry-correlated traversal proxy

です。

同じ理由で、Rustの (\Sigma_{\mathrm{kd}}) を最大化した入力がC++のkd-tree traversalも最大化するという保証はありません。Pareto frontier上で両エンジンの時間順序が異なるという結果は、この懸念と整合しています。

解決策は二つです。

1. C++解析buildで実際のnode visitsを計測する
2. C++とRustで別々の(\Sigma_{\mathrm{kd}})を使い、cross-language共通なのは入力bytesと(\Sigma_{\mathrm{nbr}})などのアルゴリズムtraceだけとする

現稿のままなら、Table VIの係数名を変更し、per-node unit costという解釈を撤回する必要があります。

## 3. Work modelからper-point fixed costが抜けている

Equation (1)にはsearch、kernel、solveはありますが、per-point transformやper-query fixed overheadが明示的に入っていません。一方、`cache-hostile`と`subnormal`では、まさにそのper-point fixed overheadが支配的であり、二項回帰の最大LOOCV errorがC++ 75%、Rust 92%になっています。

これは単なる回帰上の外れ値ではなく、work modelに必要な軸が一つ欠けている証拠です。

カウンタ形式で次のように書く方が明快です。

[
T
\le
c_0
+c_{\mathrm{pt}}N_{\mathrm{pts}}
+c_{\mathrm{nbr}}\Sigma_{\mathrm{nbr}}
+c_{\mathrm{kd}}\Sigma_{\mathrm{kd}}
+c_{\mathrm{solve}}N_{\mathrm{iter}},
]

ここで、

[
N_{\mathrm{pts}}=P,N_{\mathrm{pass}}
]

です。

このモデルなら、現在の「per-point constant overhead」という分析と一致します。回帰にも (N_{\mathrm{pts}}) を追加すべきです。

また、現在のEquation (1)では (T_{\mathrm{solve}}) が (N_{\mathrm{pass}}) 回発生するように見えますが、initial passにはNewton solveがないため、厳密には (N_{\mathrm{iter}}) 回です。上限として安全ではありますが、正確なdecompositionとしては修正した方がよいです。

## 4. 「Every term is enforced by construction」はTable XIIと一致しない

Layer 1では「Equation (1)のevery termがRust engineでenforced」と述べていますが、Table XIIでは、

* (P\le1500): preprocessing assumption
* deployment (K\le27): map pipeline assumption
* (N_{\mathrm{leaves}}): memory-parametric
* buffer capacity超過: one-time allocation

となっています。

したがって正確には、

> For fixed external parameters (P) and (N_{\mathrm{leaves}}), the internal multiplicative terms (N_{\mathrm{iter}}) and (K) are enforced by construction.

です。

同様に、「engine-API worst case」という名称も少し危険です。C++ engine APIは (D) の外も受け入れ、tile multiplicityとともにコストが増えるからです。abstractの

> engine-API worst case

は、例えば次に変えた方が正確です。

> bounded-neighbor comparison tier

または、

> engine tier restricted to the certified domain (D_K)

## 5. Search ablationは初期条件が公平ではない

Table IIでは、hill-climbが全seedでevaluation 1から(\Sigma_{\mathrm{nbr}})最大値を達成しています。これは論文自身が述べるとおり、domain-informed seed genomeが既に解析最大値にあるためです。一方、random samplingはそのseedから開始していません。

したがって、

> hill-climbがrandom samplingよりkernel maximumを見つけやすい

という比較にはなっていません。比較されているのは、

* hand-engineered optimal seed + hill climb
* random initialization

です。

この結果から強く主張できるのは、

* 解析構成が(\Sigma_{\mathrm{nbr}})最大値を達成した
* hill-climbがその状態から(\Sigma_{\mathrm{kd}})を35%増やした
* counter fitnessはwall-clock fitnessより再現可能だった

という三点です。

必要なablationは次です。

* hand-built seed only
* same seed + hill-climb
* same seed + random mutations
* random initialization + hill-climb
* random initialization + random sampling

また、wall-clock fitnessの二つのchampionの差は、12,009,768対12,009,329で約0.004%です。「異なるchampionになった」だけでなく、time rankや最終fitness差も報告すると説得力が増します。

そして`search-00`はRustのtime-worstではありません。Pareto candidateが1.1%上回っているため、abstractや本文の`worst input`は、原則として

> counter-extremal input

または、

> high-work frontier input

と呼ぶ方がよいです。

## 6. Bridge experimentには設計上の不均衡と記述ミスがある

bridge experimentを追加した判断自体は正しいです。しかしTable IXでは、

* Profile Bのsynthetic側: 複数sessionのpooled campaign
* Profile A: 1 session、100 samples/cell

となっており、特にmaximumの比較ではsample数が一致していません。最大値はsample数に依存するため、A/B max ratioを評価するなら、同じsample数・同じsession構造で測る必要があります。

また、次の記述は数値と逆です。

> every cross-engine conclusion ... survives under Profile A with wider margins

例えば`legal-worst`では、

[
\text{Profile B ratio}
======================

120.8/243.4
\simeq0.50,
]

[
\text{Profile A ratio}
======================

121.7/201.8
\simeq0.60.
]

Rustは依然として速いものの、Profile Aでは相対的な差は**狭く**なっています。`search-00`や`legal-osc`でも同じ傾向です。したがって、

> survives under Profile A, although the relative speedup narrows

と直す必要があります。

さらに、

> isolation flags themselves tax the C++ engine by 37–42 ms

という因果表現は強すぎます。同一boot内でisolated coreとnon-isolated coreを比較しても、物理core差やboot-time configurationとの交互作用が残ります。因果を確立するなら、

* 同じ物理core
* isolcpus/nohz_full/rcu_nocbsあり・なしの二つのboot
* 同じSMT、IRQ、周波数、binary、allocator
* 同じsample数と交互測定

が必要です。

現状では、

> Profile B is associated with a 37–42 ms higher C++ cost; the responsible mechanism remains unresolved.

程度が妥当です。

## 7. Profile Aの記述に直接的な矛盾がある

Section V-Iでは、Table VIIIのtiming rowsはmeasurement policyに従うProfile A結果だと明記されています。

一方、Threats to Validityでは、

> the real-data replay ... still carries pre-protocol timing (Profile-A re-capture pending)

と書かれています。

これは明確なstale sentenceです。投稿前に必ず解消してください。

同様に、Table IIIの

> 300+3000 pooled across sessions

という表記も意味が分かりません。300 samplesと3,000 tail samplesを合算したのか、fixtureによって異なるのか、全8 fixtureで3,300 samplesなのかを明記すべきです。V-Lでは3×1,000 samplesをtail-claim fixturesに対して実施したと読めるため、現在はsample accountingが不透明です。

## 8. 実データ比較はcertified subsetと全frameを分けるべき

Table VIIIのC++/Rust timing distributionは501 on-map frames全体で計算されていますが、そのうち28件はiteration countが異なります。したがってこの表は、

* system-level behavior comparisonとしては有効
* equal-work implementation comparisonとしては不純

です。

次の二表に分けることを推奨します。

1. **All 501 on-map frames**
   実システムとして各engineが示すlatency distribution

2. **473 certified frames only**
   equal-workが確認された直接比較

28 divergent framesについては別に、

* C++ timing
* Rust timing
* iteration差
* pose/score差
* (\Sigma_{\mathrm{nbr}})差

を報告するとよいです。

また、「preprocessing contracts hold empirically」と言える根拠として現在示されているのは、主に (P\le1500) とobserved (K\le9) です。tile disjointness、voxel alignment、duplicate-free、crop、downsample-cell invariantまで検証したのであれば、そのlegality verifierの結果を明記してください。検証していないなら、

> the observed (P) and (K) were consistent with the preprocessing contracts

に弱めるべきです。

abstractでも「57-minute drive」とだけ書くと、22,416件すべてが意味のあるNDT matchだったように読めます。次のようにするのが透明です。

> a 57-minute capture containing 501 on-map matching frames

## 9. AArch64結果は「成功」だけでなく、実時間上の不成立を前面に出すべき

Raspberry Pi 4上では、

* engine-tier `search-00`: 約9.85秒
* `legal-worst`: 約1.50秒
* `legal-osc`: 約0.84秒

です。10 Hzの100 ms budgetに対し、`legal-worst`でも約15倍、engine-tierでは約98倍です。

これは単なる「より大きなheadroomが必要」という結果ではありません。現在のserial configurationは、このtarget上ではinput contractだけでは10 Hzを満たせない、という明確なfeasibility resultです。

論文では次を明言すべきです。

> The current serial Rust configuration is not schedulable at 10 Hz on the evaluated Cortex-A72 target, even on the deployment-tier witness.

そして今後の課題はcontract enforcementだけでなく、

* source-point数削減
* algorithm redesign
* parallelization
* SIMD最適化
* より高速なtarget

になります。

また、pure-Rust libmを使っていることだけでISA-independent floating-point streamが「by construction」になるわけではありません。FMA、compiler lowering、denormal mode、その他のfloating-point operationも影響します。8 fixtureでcounter一致したことは強い実験的証拠ですが、

> designed for ISA-stable execution and verified on all frozen fixtures

程度の表現が適切です。可能ならtarget上でもpose、score、trace hashを比較してください。

---

# 統計・回帰についての追加コメント

EVTについて外挿を拒否した判断は正しいです。ただし、独立性が成立しない系列に通常のbootstrapを適用して得た(q_{10^{-9}}) CIは、それ自体も厳密なconfidence intervalとは解釈できません。Table XIは診断失敗を示すための参考値として明記するか、quantile列を削除して、

* ACF
* threshold stability
* shape estimate instability
* extrapolation rejected

だけを示す方がすっきりします。

回帰についても、median LOOCV error 6–7%だけで「predictive」とすると、最大error 75–92%が隠れます。より正確には、

> predictive on the dense-neighbor and P-sweep regime, but inadequate for neighbor-sparse inputs dominated by per-point overhead

です。(N_{\mathrm{pts}})項を追加すれば、この弱点はかなり改善する可能性があります。

---

# 編集・再現性上の修正

投稿前に最低限、次を直す必要があります。

* 1ページ目の赤い著者・email TODOを削除
* Rust port、benchmark harness、data artifactのexact commitを記載
* artifact repositoryまたはDOIを示す
* `300+3000`のsample accountingを明確化
* pre-protocol環境でのみ測ったsubnormal A/Bを現行protocolで再測定
* `WCET(P)=...`を、hard boundではないため`observed envelope`または`T_{\mathrm{obs,max}}(P)`に変更
* glibc allocatorについて「有限WCETを一般に不可能にする」ではなく、「本論文のallocator/system modelでは防御可能な有限上限を与えられない」に変更
* `machine-checked`を、形式検証と混同されにくい`automatically checked by property tests`等に変更

紙面は13ページでかなり密です。Page 9–10のbridge、on-target、EVT表は情報量が多いため、stale-baselineの経緯やsubnormalの詳細をappendix/artifactへ移し、cross-language certificateに紙面を割く方が論文の芯が強くなります。

---

# 最終判定

**現稿: Weak Reject / Major Revision**

前稿と比べれば、明確に採択圏へ近づいています。Kの幾何上限、測定環境、real-data denominator、EVTの扱いなどは、査読コメントへの非常に良い応答です。

ただし、現在の論文で最も荷重を受けている梁は依然として、

> equal iteration count → equal work → Rust counter worst case transfers to C++

という部分です。この含意は成立しておらず、allocation countもpass数の補助証拠にしかなりません。ここをinstrumented C++ traceまたは同等のcertificateで埋め、`bit-exact`という表現を実際の証拠強度に合わせれば、論文の中核はかなり強くなります。

優先順位は次の通りです。

1. C++/Rustのper-input trace certificateを追加
2. `bit-exact over D`を撤回または再定義
3. work modelにper-point項を追加し、実装別kd counterを使う
4. bridge experimentのsample数と因果記述を修正
5. real-data timingを473 certified framesと501 all framesに分離
6. Pi 4上で10 Hz不成立という結果を明示

この六点が直れば、main-trackでも十分に競争力のある、産業的にも研究的にも面白い論文になります。
