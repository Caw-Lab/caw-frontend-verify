# コントラクトの基準 JSON の形式(v1)

`contract-check` が読む、基準ファイル。例: `reference_testnet_97cd13f3.contracts.json`(テストネット、上流 `97cd13f3`)。

**考え方:** ファイルが「どのコントラクトがあり、互いにどう繋がっているべきか」を**規則として持つ**。チェッカーは、規則を実際のチェーンで実行するだけで、アドレスや関係をコードに持たない。基準が壊れていたら、**合格にせず、拒否する**(`INVALID`)。

## 構造

```json
{
  "schemaVersion": 1,
  "kind": "caw-contract-reference",
  "network": "testnet",
  "release": "どのリリースの基準か(人が読む)",
  "createdAt": "2026-11-13",
  "notes": ["basis の意味など(人が読む)"],
  "chains":    { "L1": { "chainId": 11155111, "eid": 40161 }, "L2": { ... }, "L2b": { ... } },
  "contracts": { "L1": { "CawProfile": { "address": "0x…", "basis": "published", "code": { … } }, ... }, ... },
  "rules":     [ ... ]
}
```

- `chains`: チェーンの鍵(`L1`、`L2` など)ごとに、`chainId` と LayerZero の `eid`。RPC が名乗るチェーン ID が、これと違えば不一致。
- `contracts`: チェーンごとのコントラクトの名前 → `address`、`basis`、`code`。すべてのアドレスに、コードがあるか、**コードが固定した値と一致するか**を確かめる(下の「コードの固定」)。
- `basis`(根拠。必須):

| basis | 意味 | 保証の強さ |
|---|---|---|
| `published` | 上流のリポジトリ(`deployments.ts`、`addresses.ts`)が、そのリリースで載せている値 | 公開者の主張 |
| `observed` | 基準を作った日に、チェーンから読み取って固定した値(リポジトリに載っていないもの) | **後の変更を検出できる**。ただし、その値が正しいことの独立の証明ではない |
| `external` | 第三者のコントラクト(LayerZero のエンドポイント、SP1 の verifier、スワップのルーター、WETH)を、同じく観測で固定した値 | 同上 |

## 規則(`rules`)

| type | 意味 | 追加の項目 |
|---|---|---|
| `link` | `contract.call()` が返すアドレスが、`target` のコントラクトと一致する | `call`(例 `"minter()"`)、`target: {chain, contract}` |
| `zero` | `contract.call()` がゼロアドレスを返す(放棄済み、無効など) | `call` |
| `value` | `contract.call()` が整数 `expect` を返す(`bypassLZ()` など) | `call`、`expect`(整数) |
| `peer` | LayerZero の `peers(eid)` が、`target` のコントラクトを指す | `eid`、`target` |
| `delegate` | エンドポイントの `delegates(contract)` が、`target` と一致する | `endpoint: {chain, contract}`、`target` |

すべての規則に `chain` と `contract`(検査する側)がある。`call` は引数なし(`name()`)で、`peers` と `delegates` は専用の規則で扱う。

## 検査の結果

| 結果 | 意味 |
|---|---|
| `OK` | 一致 |
| `MISMATCH` | 期待と違う値が返った |
| `NOCODE` | そのアドレスにコードがない |
| `CALLFAIL` | 呼び出しが失敗した(関数がない、など) |
| `INVALID` | **基準そのものが壊れている**(下記)。チェーンへの問い合わせはしない |

総合判定: `PASS`(すべて OK)/ `FAIL`(1件でも MISMATCH・NOCODE・CALLFAIL)/ `INVALID`。終了コードは 0 / 1 / 2。

## 基準を拒否する条件(`INVALID`)
- `schemaVersion` が 1 でない。`kind` が違う。
- `chains`、`contracts`、`rules` のどれかが空(**何も検査しない基準を、合格にしない**)。
- アドレスが 20 バイトの 16 進でない。ゼロアドレス。
- `basis` がない、または未知の値。`code` がない、または形が不正(`maskedHash`、`mask`、`evidence`、`links`)。
- `code.links` の指す先が、`contracts` にない。
- `recompile-*` の根拠があるのに、`provenance.recompile`(`sourceCommit`、`compiler`、`compilerSha256`、`settings`、`dependencies`)がない。`recompile-except-metadata` に、`provenance.olderCompiler.<名前>` がない。
- 規則が、`contracts` にないコントラクトを指す(名前の誤りを含む)。
- 規則の型が未知。必要な項目がない(`value` の `expect`、`peer` の `eid` など)。

これは、上流の Verifier の F-02(`files` が空でも合格になる)と同じ種類の穴を、最初から塞いだもの。

## 作り方と限界
- 生成: `make_contract_reference.py`(上流のリポジトリの `deployments.ts`、`addresses.ts` と、チェーンの観測から作る)。`observed`/`external` の値は、**作った日の状態の固定**で、独立の保証ではない。
- 未対応: ローカルでの再コンパイル(下記)、メインネット、ネットワークごとの複数の基準。
- チェーンの鍵ごとの RPC は、今はチェッカーのコードに固定(`L1`、`L2`、`L2b`)。

## コードの固定(`code`、バイトコードの照合)

各コントラクトの実行時コードを、デプロイ後に変えられない部分を除いて固定する。

```json
"code": {
  "maskedHash": "0x…",                       // 下の領域をゼロにしたコードの keccak256
  "mask": [[2265, 32], [6048, 32]],          // immutable の領域 [開始バイト, 長さ]
  "evidence": "sourcify-exact-match",
  "links": [ { "start": 11764, "length": 20, "target": { "chain": "L1", "contract": "SessionMessageParser" } } ]
}
```

- **`mask`(immutable):** コンストラクタの引数でコードに埋め込まれる値。デプロイごとに違うので、除いて比べる。
- **`links`(リンクされたライブラリ):** コードの中に、ライブラリのアドレス(20 バイト)が埋め込まれる場合、その位置と、**指す先を `contracts` の別のコントラクトとして列挙**する。検査は、(1)その位置のバイト列が、指す先のアドレスと一致するか、(2)指す先のコード自体が固定した値と一致するか、の両方を見る。**単にライブラリのアドレスを除いて比べると、悪意のあるライブラリにリンクした偽物を見逃す**ため、この形にした(`CawProfileLedger` が `SessionMessageParser` をリンクしている)。
- **`evidence`(根拠の強さ):**

| evidence | 意味 | 強さ |
|---|---|---|
| `recompile-identical` | **自分たちで、独立に再コンパイルした結果**が、チェーンのコードと、メタデータも含めて一致する。リポジトリの特定のコミット、`package-lock.json` が固定する依存(sha512 の整合性を検証)、公式の solc(sha256 を公式の一覧で検証)でコンパイルし、solc 自身が出す immutable とリンクの領域を除いて比べる。条件は `provenance.recompile` に記録する | **最も強い**(Sourcify の再コンパイルに頼らない) |
| `recompile-except-metadata` | 再コンパイルの結果が、末尾のメタデータを除いて一致する(古いコンパイラ、別のソースの文面など)。条件は `provenance.olderCompiler.<名前>` に記録する | 強い(メタデータだけ違う) |
| `sourcify-exact-match` | Sourcify の再コンパイル結果と、チェーンのコードが、immutable とリンクを除いて、**メタデータも含めて**一致する。**この一致は、基準を作るときに、こちらのバイト比較で確かめる**(Sourcify の判定を鵜呑みにしない) | 強い(ソースに結びつく) |
| `sourcify-match` | メタデータ(末尾の CBOR)を除いて一致 | やや強い |
| `same-code-as:<chain.name>` | 別のチェーンの、検証済みのコントラクトと、同じ領域を除いて**同一のコード**(L2・L2b の `CawActions` などが、L1 の検証済みと同一) | 検証済みに結びつく |
| `observed-only` | 作った日にチェーンから読んだコードのハッシュ(領域は除かない)。ソースの根拠はない | **後の変更の検出だけ** |

- 検査の最後に、`CODE EVIDENCE` として、根拠の内訳を表示する(`observed-only` が多いほど、保証は弱い)。
- 生成: `add_code_pins.py`(`make_contract_reference.py` の出力に、`code` を足し、見つかったライブラリを `contracts` に足す)。

### 何が保証され、何が保証されないか
- 保証される: チェーン上のコードが、固定した値と同じ(= 検査の時点まで、コードが変わっていない)。`sourcify-*` と `same-code-as` のものは、さらに、**固定した値が、公開されたソースとコンパイル設定に結びつく**。
- 保証されない:
  - `sourcify-*` の根拠は、Sourcify の再コンパイル結果を、こちらのバイト比較でチェーンと突き合わせたもの。Sourcify の再コンパイルが正しい、という信頼が残る。`recompile-*` は、この信頼を要しない(依存は整合性ハッシュ、コンパイラは公式の sha256 で検証)。
  - ソースが、リポジトリの特定のコミットと一致するかは、**基準を作るときに別途確かめる**(`97cd13f3` の場合、主要な13ファイルが完全に同一だった。メモ §9)。依存ライブラリ(OpenZeppelin、LayerZero)のファイルは、確かめていない。
  - `observed-only` のもの(`MintableCaw`、L2・L2b の `CawActionsArchive`、`CawChallengeRelay`)は、ソースの根拠がない。Sourcify への検証の提出が、解消の道(第三者の公開サービスへの書き込みになるので、事前の確認が要る)。

---
License: MIT. Copyright (c) 2026 zinsanjp and contributors.
