# 開發

```
python -m unittest                    # 單元測試和端到端測試（用假檢查員，不需要 Go；有 dotnet 時另外測 C# 工具的建置隔離）
python selftest.py                    # 全部範例
python selftest.py go                 # Go 範例專案的全部情境（含 gate.sh），要 Go 和網路（第一次裝 gocyclo、gremlins）
python selftest.py csharp             # C# 範例專案的全部情境（含照 README 掛上、gate.sh），要 .NET SDK 10 和網路
python selftest.py go --only 排除     # 只跑名稱含「排除」的情境
```

`dev/` 底下的兩支腳本只有維護者能跑：它們要用到維護者本機上另外兩個 repo（之前用的量測工具，以及一個真實的 Go 專案），路徑寫死在腳本裡。

```
python dev/parity_qt.py sample        # 和之前用的量測工具對照範例專案的 CRAP 表和抓錯計數
python dev/parity_qt.py bethere       # 同上，對那個 Go 專案的暫存複本，抓錯計數要 45 分鐘左右
python dev/walkthrough_bethere.py     # 照 README，在那個 Go 專案的暫存複本上掛 submodule、複製範本、走一遍
```

selftest 的 gate.sh 情境把這個 repo 的 `git ls-files` 複製到範例的 `tools/referee/`（像 submodule 一樣），再照 README「安裝到專案」的步驟複製範本，所以只有已經加入 git 的檔案會被複製。

## 誰扮演什麼角色

| 角色 | 是誰 | 負責 | 不負責 |
|---|---|---|---|
| **裁判** | quality-referee（掛在專案的 `tools/referee/`） | 找出這次改到哪些行和函式；算 CRAP、抓錯率、測到率；比對排除清單；判定過或不過；寫報告；回傳結束碼 | 不認得任何語言，不跑測試，不呼叫任何量測工具 |
| **記分表** | [docs/合約.md](docs/合約.md) 定的兩種 JSON：函式表、改壞版本表 | 裁判和檢查員之間唯一的約定。格式不對，裁判直接以結束碼 2 停下 | — |
| **檢查員** | 標準檢查員（`inspectors/go.py`、`inspectors/csharp.py`），或專案自己寫的程式 | 照裁判給的 context 量測，把原始數字填進記分表 | 不判斷過不過，不算 CRAP，不標「改了也沒差」 |
| **專案** | 各專案 repo | 寫 `.referee.json`：用哪個檢查員、哪些目錄不算、門檻多少；維護排除清單；寫測試 | 不改裁判的判定規則 |
| **簽名的人** | 審 PR、按合併的人 | 看測試有沒有被刪或改鬆；逐項核准排除清單的理由；決定門檻 | — |

判定規則、記分表和報告的格式都在這個 repo 改，改完發新版本。記分表或報告的格式一改，合約的版本就要跟著升（例如 `referee.functions/1` 升成 `/2`），各專案的自訂檢查員才知道要配合。

兩種 JSON 不要搞混：**記分表**是檢查員填、給裁判讀的；**報告**（`referee.report/2`）是裁判寫、給人和 CI 讀的。檢查員不碰報告，所以不管專案用哪個檢查員，判定規則和報告格式都一樣，不同專案的分數可以互相比較。
