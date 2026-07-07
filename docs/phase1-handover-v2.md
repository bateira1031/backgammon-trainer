# Backgammon Trainer — Phase 1 指示書 v2(Claude Code用)

## ゴール

GNU Backgammon (gnubg) をバッチ実行し、レスポンスクイズ用の**高品質データセット(JSON)**を生成する。
アプリ本体へのWASM組み込みは行わない(それはPhase 2)。成果物は静的JSONファイルであり、GitHub Pagesにそのまま同梱できること。

## 実行環境(セットアップ済み・確認のみでよい)

- Windows 11 上の **WSL2 Ubuntu**
- **gnubg はインストール済み**(`sudo apt install gnubg` 実施済み)
- 作業リポジトリ: `~/dev/backgammon-trainer`(GitHub: bateira1031/backgammon-trainer、GitHub Pages公開中)
- gh CLI 認証済み

## Git運用

- ブランチ `feature/dataset-v2` を切って作業する
- `main` への直接pushはしない(GitHub Pagesが即時公開されるため)。完了後にマージはユーザーが判断
- スクリプトは `scripts/`、生成データは `data/` に配置

## 背景

- ver.1 PWA は完成・公開済み: https://bateira1031.github.io/backgammon-trainer/index.html
- 現状のレスポンスクイズは手入力の336問(`index.html` 内 `PRESET_PROBLEMS`)。ダミー選択肢が人力なので信頼性が低い
- これを「gnubg解析による上位4手+エクイティ」に置き換えたい

## アプリの現行仕様(互換性のために必要な知識)

### ムーブ表記
常に**白(ユーザー)視点の24→1方向**の表記。例: `24/13`, `8/5 6/5`, `13/7*(2)`, `24/20(2) 13/9(2)`
- `*` = ヒット、`(n)` = 同じ移動をn回
- 相手(グレー)のオープニングも同じ表記で保持し、アプリ側で `applyGrayMove()` が24点対称に変換して適用する

### オープニングキー(16種)
`65 64 63 63alt 62 61 54 53 52 51 43 42 41 32 31 21`
- `63` = 24/18 13/10、`63alt` = 24/15(2大ブック手を両方収録)
- オープニングにゾロ目は存在しない(ルール上)

### レスポンス側のロール(21種)
非ゾロ目15種 + ゾロ目6種(66, 55, 44, 33, 22, 11)

### 生成すべき局面数
16オープニング × 21ロール = **336局面**

### 盤面配列仕様(index.html準拠)
index 0-23 = ポイント1-24、正の数=白の枚数、負の数=グレーの枚数。
初期配置: `b[23]=2, b[12]=5, b[7]=3, b[5]=5, b[0]=-2, b[11]=-5, b[16]=-3, b[18]=-5`

## タスク

### Task 1: gnubg環境確認
```bash
gnubg --version
gnubg -t        # 対話モードで help を確認して exit
```
- **Python埋め込み**(`gnubg -p script.py`)が使えるか確認する(`gnubg.findbestmove()`, `gnubg.evaluate()` 等)
- UbuntuのaptパッケージはPythonサポート有無がビルドにより異なる。**使えない場合はCLIの `hint` コマンド出力をパースするフォールバック**で実装してよい(`gnubg -t -q < commands.txt` 方式)
- どちらの方式を採ったかを最後に報告すること

### Task 2: データセット生成スクリプト
`scripts/generate_dataset.py`(gnubg内蔵Python or 外部ドライバ+CLIパースの2段構成)

処理フロー:
1. 初期配置から、各オープニングキーのグレー側ムーブを適用した局面を構築
2. その局面で白のロール(21種)ごとに gnubg の hint を実行
3. 上位4手(候補が4未満ならある分だけ)とエクイティを取得
4. JSONに書き出し

解析設定: **2-ply、cubeless、money play** を基準とする。
スクリプトは**再実行可能・冪等**にすること(途中失敗からの再開ができるとなお良い)。

### Task 3: 出力フォーマット

`data/response-quiz-v2.json`:
```json
{
  "version": 2,
  "generated": "YYYY-MM-DD",
  "engine": "gnubg <version> 2-ply cubeless",
  "problems": [
    {
      "opening": "65",
      "myRoll": "31",
      "moves": [
        { "m": "8/5 6/5",      "eq": 0.000 },
        { "m": "24/23 13/10",  "eq": -0.118 },
        { "m": "24/20",        "eq": -0.152 },
        { "m": "13/10 6/5",    "eq": -0.161 }
      ]
    }
  ]
}
```
- `moves[0]` が常に最善手。`eq` は最善手との差分(負の値)で記録
- ムーブ表記はアプリの表記規則に正規化すること。gnubg出力はほぼ互換だが、`(n)` 縮約とヒット `*` の有無をアプリのパーサ `parseWhiteMoves()`(正規表現: `(\d+)\/(\d+)\*?` + `(n)`)が読める形に揃える
- `bar/`, `/off` は今回の局面群では出ない想定。もし出たらエラーとして報告

`data/openings-v2.json`(オープニング暗記用):
```json
{
  "openings": [
    { "roll": "31", "best": "8/5 6/5", "alternatives": [{ "m": "24/23 13/10", "eq": -0.11 }] }
  ]
}
```

### Task 4: 検証
- 336局面すべてが揃っているか(件数チェック)
- 既知のブックとのサンプル照合: 65→24/13、31→8/5 6/5、63は 24/18 13/10 と 24/15 が僅差、など数件
- 全ムーブ文字列が `parseWhiteMoves()` 互換かを機械チェック(検証スクリプトを `scripts/validate_dataset.py` として残す)
- 検証結果を `docs/dataset-validation.md` に記録

### Task 5(余力があれば): ピップカウント用実戦局面
gnubg自己対戦から局面をサンプリングし、`data/pip-positions.json` に書き出す(100局面程度):
```json
{ "board": [24要素の配列], "phase": "race|holding|prime|bearin" }
```
phase分類の目安: コンタクト無し=race、アンカー保持=holding、3連続ポイント以上=prime、全駒ホームボード付近=bearin。厳密でなくてよい。

## 完了時の報告内容

1. 採用した方式(Python API / CLIパース)
2. 生成件数と検証結果のサマリ
3. ブック照合で気になった点(僅差の手、想定と違った最善手など)
4. コミット済みブランチ名

## やらないこと(スコープ外)

- index.html の改修(JSON読み込み・エクイティ表示UI)は次のタスク
- Phase 2(bgweb-api WASM統合)
- mainへのマージ・デプロイ
