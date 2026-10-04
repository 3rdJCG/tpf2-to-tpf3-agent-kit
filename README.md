# tpf2-to-tpf3-agent-kit

**A toolkit for porting Transport Fever 2 (TpF2) rail vehicle mods to Transport Fever 3 (TpF3).**
One command builds a TF3 mod from a TF2 mod. It is made to be handed, together with its procedure (a Skill), to a
coding agent such as Claude Code, which can then take a port from start to in-game check.

[日本語は下にあります / Japanese below](#日本語)

- **Its own conversion.** Models, materials, meshes and animations are converted TF2 → TF3 by running the game's
  own Lua. The result is byte-identical to the official Model Editor's Bulk Convert on 31 mods. The Model Editor is
  never opened.
- **Fixes what TF3 does differently**: texture orientation and format (DDS), material types, lights, exhaust and
  steam, sound (48 kHz), consists, translations, and broken references in the original mod.
- **Draws the icons.** The five purchase-menu icons, with the editor's framing, track and colour adjustment.
- **Checks in the game.** Runs the game's own load validation without a window and photographs every model in
  game. Optionally builds a test line, runs a train on it, and checks top speed and horn.

Tested end to end on 31 mods by different authors: diesel, electric and steam locomotives, DMUs, EMUs, coaches,
sleepers and wagons.


## Requirements

- Windows
- Transport Fever 3 (Steam)
- The TF2 mods to port (subscribed on the Steam Workshop and downloaded)
- Python 3.10 or later

## Getting started

```
git clone <this repository>
pip install -r tpf2-to-tpf3-agent-kit/requirements.txt

mkdir my-tf3-ports
cd my-tf3-ports
python ../tpf2-to-tpf3-agent-kit/port.py paths
```

Your own files (vehicle configs, logs) live in a **workspace** separate from the tool, `my-tf3-ports` above, so
updating the tool never touches them. Running a command in a folder that has `vehicles/` or `local_settings.json`
makes it the workspace (the environment variable `TPF3KIT_WORKSPACE` works too).

`port.py paths` shows whether Steam, TF3, the staging area and the TF2 workshop folder were found. They are looked
up in the registry and Steam's library list. If something is wrong, put a `local_settings.json` in the workspace:

```json
{
    "tf3": "E:/SteamLibrary/steamapps/common/Transport Fever 3",
    "tf2_workshop": "E:/SteamLibrary/steamapps/workshop/content/1066780"
}
```

Keys: `steam` / `tf3` / `tf3_local` (`userdata/<ID>/3493540/local`) / `tf2_workshop` / `vehicles` /
`helper_loco` (the locomotive that pulls coaches in the drive test) / `name_prefix` (a mark in front of every
ported vehicle's name, e.g. `"◆"`).

## Usage

Below, `port.py` means the tool's `port.py` (e.g. `python ../tpf2-to-tpf3-agent-kit/port.py`).

```
# 1. Write the vehicle config (vehicles/<name>.json; warns about what needs hand work)
python port.py new <workshop id> <name> <modId>

# 2. Everything (a few minutes; no screen, no mouse)
python port.py <name> all

# 3. Check the look in game (close the game first; photographs every model -> logs/smoke/)
python port.py smoke <name>
```

Read the counts it prints (material types, texture formats, lights, models). A number that is off from usual is how
silent breakage shows. Finally, enable the mod in TF3, start a game within the vehicle's years, and buy one at a
depot.

For the config format, see [examples/vehicles/](examples/vehicles/) and
[docs/pipeline.md](docs/pipeline.md#the-vehicle-config).

### Commands

`python port.py` with no arguments lists them.

| Command | What it does |
|---|---|
| `<name> all` | Everything: `build convert post genicons icons validate check gamecheck`, in order. Each also runs on its own |
| `new <id> <name> <modId>` | Writes a vehicle config template |
| `summary <name...>` | Counts and errors from `logs/port_<name>.log` (after porting several in a batch) |
| `smoke <name...>` | Starts the game and photographs every model |
| `drive <name...>` | (Optional) Builds a test line and runs a train: top speed, sound, horn, lights. Takes a few minutes |
| `gamelog [modId]` | The game's log, grouped by mod |
| `editor` | Opens the Model Editor with its log kept (some errors otherwise only flash by on screen) |
| `paths` | Shows what was found where |
| `golden` / `compare-convert` / `compare-icons` / `calibrate` | For working on the converter. Not needed for porting |

`--engine editor` makes the conversion and the icons with the official Model Editor instead, by driving its GUI
(needs a display at least 1920 px wide; see [docs/model-editor.md](docs/model-editor.md)).

## With a coding agent

Every mod is built differently, and deciding what needs fixing takes judgement. To let an AI agent make those
calls, the procedure and the pitfalls are written down:

- [AGENTS.md](AGENTS.md): the repository's rules and how to check changes
- [.claude/skills/tf2-to-tf3-port/](.claude/skills/tf2-to-tf3-port/SKILL.md): the porting procedure (a Claude Code
  Skill). Link or copy it into your workspace's `.claude/skills/` so an agent working there can use it
- [docs/troubleshooting.md](docs/troubleshooting.md): from symptom to cause

## Documentation

| | |
|---|---|
| [docs/tf2-tf3-differences.md](docs/tf2-tf3-differences.md) | What differs between TF2 and TF3. Useful for porting by hand too |
| [docs/pipeline.md](docs/pipeline.md) | Each step, the rules, the vehicle config |
| [docs/game-testing.md](docs/game-testing.md) | The game's hidden command line and the automated tests |
| [docs/model-editor.md](docs/model-editor.md) | Driving the Model Editor (`--engine editor`) and fixing it when the UI changes |
| [docs/troubleshooting.md](docs/troubleshooting.md) | From symptom to cause |
| [docs/roadmap.md](docs/roadmap.md) | How the conversion was rebuilt, and what is open |

## Layout

```
port.py             entry point (every feature is a subcommand)
tf3port/            the code
  cli.py            the porting steps and their order
  build.py ...      one module per step (materials, textures, lights, sounds ...)
  convert/          the TF2 -> TF3 conversion (runs the game's Lua in lupa)
  render/           icon drawing (numpy)
  game/             starting the game, the smoke and drive tests
  editor.py         Model Editor automation (--engine editor)
  dev/              tools for working on the converter
examples/vehicles/  example vehicle configs (made up)
docs/               findings and explanations
```

In the workspace you get `vehicles/` (your configs), `logs/` (logs and screenshots) and `local_settings.json`.

## License

[MIT](LICENSE), covering the tool and its documentation.
`tf3port/convert/vendor/tl.lua` (the Teal compiler) is included under the MIT license. No game files are included;
they are read from your own TF3 install at run time.

---

## 日本語

**Transport Fever 2 (TpF2) の鉄道車両MODを Transport Fever 3 (TpF3) へ移植するツールキットです。**
コマンド1本で TF2 の MOD から TF3 の MOD を組み立てます。Claude Code などのコーディングエージェントに
手順書(Skill)ごと渡して、移植からゲーム内の確認までを任せられるように作ってあります。
ドキュメント(`docs/`)は英語です。

- **変換は自前。** TF2 → TF3 のモデル・マテリアル・メッシュ・アニメーションの変換は、ゲーム自身の Lua を実行して
  行います。公式 ModelEditor の Bulk Convert と、31本の MOD でバイト単位まで一致します。ModelEditor は開きません。
- **TF3 との差分を補正。** テクスチャの向きと形式(DDS)、マテリアル型、ライト、排気・蒸気、音(48 kHz)、編成、
  翻訳、元の MOD の壊れた参照など。
- **アイコンも描く。** 購入メニューの5種類のアイコンを、エディタと同じ枠取り・線路・色補正で描きます。
- **ゲームで確かめる。** ゲーム本体の読み込み検証を画面なしで回し、全モデルをゲーム内で撮影します。
  任意で、試験線を自動で作って列車を走らせ、最高速度と警笛を確かめます。

機関車・電機・蒸機・気動車・電車・客車・寝台・貨車の、作者の異なる31本で通して確認しています。


### 必要なもの

- Windows
- Transport Fever 3(Steam 版)
- 移植元の TF2 MOD(Steam ワークショップでサブスクライブしてダウンロード済みのもの)
- Python 3.10 以上

### はじめに

```
git clone <このリポジトリ>
pip install -r tpf2-to-tpf3-agent-kit/requirements.txt

mkdir my-tf3-ports
cd my-tf3-ports
python ../tpf2-to-tpf3-agent-kit/port.py paths
```

自分のファイル(車両の設定、ログ)は、ツールとは別の**ワークスペース**に置きます(上の例では `my-tf3-ports`)。
ツールを更新しても自分のファイルには触れません。`vehicles/` か `local_settings.json` のあるフォルダでコマンドを
実行すると、そこがワークスペースになります(環境変数 `TPF3KIT_WORKSPACE` でも指定できます)。

`port.py paths` は、Steam・TF3・staging area・TF2 ワークショップの場所が見つかったかを表示します。レジストリと
Steam のライブラリ一覧から自動で探します。違っていれば、ワークスペースに `local_settings.json` を置いて上書きします
(書き方は英語版の例を参照)。キーは `steam` / `tf3` / `tf3_local` / `tf2_workshop` / `vehicles` /
`helper_loco`(走行テストで客車を牽く機関車)/ `name_prefix`(移植した車両の名前に付ける印。例 `"◆"`)。

### 使い方

以下、`port.py` はツールの `port.py` のことです(例: `python ../tpf2-to-tpf3-agent-kit/port.py`)。

```
# 1. 車両の設定を作る(vehicles/<名前>.json。手作業が要りそうな点を警告する)
python port.py new <ワークショップID> <名前> <modId>

# 2. 全工程(数分。画面もマウスも使わない)
python port.py <名前> all

# 3. ゲームで外観を確認(ゲームは閉じておく。全モデルを撮影 → logs/smoke/)
python port.py smoke <名前>
```

出力される件数(マテリアル型、テクスチャ形式、ライト、モデル数)に目を通してください。いつもと違う数字が、
黙って壊れたところを見つける手がかりです。最後は TF3 で MOD を有効にし、車両の登場年代の中でゲームを始めて、
車庫で買って確かめます。

`python port.py` を引数なしで実行するとコマンドの一覧が出ます。主なもの:

| コマンド | 内容 |
|---|---|
| `<名前> all` | 全工程。ステップを1つずつ実行することもできる |
| `new` / `summary` | 車両の設定の雛形 / まとめて回したときのログの集計 |
| `smoke` | ゲームを起動して全モデルを撮影する |
| `drive` | (任意)試験線を作って列車を走らせ、最高速度・音・警笛・ライトを確かめる。数分かかる |
| `gamelog` / `editor` / `paths` | ゲームのログ / ログを残して ModelEditor を開く / 見つかった場所 |

`--engine editor` を付けると、変換とアイコンを公式 ModelEditor の GUI を自動操作して作ります(画面の横幅 1920 以上が必要)。

### コーディングエージェントで使う

移植は MOD ごとに作りが違い、補正が要る箇所の見極めに手間がかかります。その判断を AI エージェントに任せられるよう、
手順と落とし穴を文書にしてあります。[AGENTS.md](AGENTS.md)(約束事と確かめ方)、
[Skill](.claude/skills/tf2-to-tf3-port/SKILL.md)(移植の手順。ワークスペースの `.claude/skills/` にリンクかコピーして使う)、
[docs/troubleshooting.md](docs/troubleshooting.md)(症状から原因を引く表)。

### ライセンス

[MIT](LICENSE)。ツールとドキュメントが対象です。
`tf3port/convert/vendor/tl.lua`(Teal コンパイラ)は MIT ライセンスで同梱しています。
ゲーム本体のファイルは同梱せず、実行時に手元の TF3 から読みます。
