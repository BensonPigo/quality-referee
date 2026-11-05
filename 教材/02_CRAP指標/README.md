# 02 CRAP 指標：量測程式的結構風險（Go 實作教學）

> 對應指南章節：《企業級 AI 代理人品質驗證與自動化防線架構指南》§2.2 第二重約束
> 前一課：`01_單元測試`（考卷與答案卷）

## 核心概念

第一重約束（單元測試）只檢查「算出來的答案對不對」，不管程式寫得多亂。一個塞了 30 個 `if` 的函式，只要測試全綠就會放行。CRAP 指標用來量測程式的**結構風險**：函式越複雜、測試越少，分數越高。

$$
\text{CRAP} = C^2 (1-p)^3 + C
$$

| 符號 | 意思 | 本專案用什麼算 |
|---|---|---|
| C | 圈複雜度：函式裡有幾條路可以走。從 1 開始，每遇到 `if`、`for`、`case`、`&&`、`||` 就加 1 | [gocyclo](https://github.com/fzipp/gocyclo) |
| p | 覆蓋率：測試實際執行過這個函式多少比例的敘述 | `go test -coverprofile` |

最重要的一點：**測試寫得再完整（p = 100%），CRAP 最低也只能降到 C。** 所以門檻 12 代表圈複雜度 13 以上的函式，不管測試寫得多好都過不了，只能拆小。

要守住門檻 12，各種複雜度需要的覆蓋率：

| 圈複雜度 C | 最低覆蓋率 |
|---|---|
| 1～3 | 0% |
| 4 | 21% |
| 5 | 35% |
| 6 | 45% |
| 8 | 61% |
| 10 | 73% |
| 11 | 80% |
| 12 | 100% |
| 13 以上 | 不可能 |

## 需求規格

購物車結帳金額計算規則：

1. 購物車是空的，金額為 0
2. 數量 <= 0 的商品略過不算
3. 非特價商品：會員九折、VIP 八五折；特價商品不再打折
4. 優惠券 `SAVE100`：打折後小計滿 1000 元，再折 100 元
5. 折完優惠券後滿 3000 元，再折 300 元
6. 運費：小計未滿 1000 元收 100 元；VIP 或優惠券 `FREESHIP` 免運；優惠券 `HALFSHIP` 運費 50 元

## 專案結構

```
02_CRAP指標/
├── go.mod / go.sum
├── checkout.go         # 正式程式碼：故意把所有規則塞在一個函式裡（圈複雜度 14）
├── checkout_test.go    # 測試：目前只有 2 筆
├── tools/crap/main.go  # CRAP 量測工具：結合 gocyclo 與覆蓋率，超過門檻就失敗
├── 補充_圈複雜度.md
└── 補充_認知複雜度.md
```

### CRAP 量測工具

```bash
go run ./tools/crap                      # 門檻 12（預設）
go run ./tools/crap -threshold 30        # 自訂門檻
go run ./tools/crap -baseline            # 量出現況：列出分布和改善方向，不判定成敗
go run ./tools/crap -base origin/main    # 只檢查和 origin/main 相比有改到的函式
```

後兩個參數是給「專案做到一半才導入 CRAP」用的，本課的練習用不到：

- `-baseline`：超標的函式後面會標出改善方向。圈複雜度超過門檻的標「要拆函式」，其他的標「覆蓋率要到 X%」。最後印出通過幾個、超標幾個。
- `-base`：只判定這次改到的函式（包含還沒 commit 的改動和新檔案）。沒改到的超標函式列為技術債，不影響結果。專案要是 git 儲存庫才能用。

工具會依序做三件事：

1. 執行 `go test -coverprofile`，取得每個函式的覆蓋率。**測試沒有全部通過就直接停止**，因為答案錯了，量結構沒有意義，要先修好第一重約束。
2. 用 gocyclo 計算每個函式的圈複雜度。
3. 算出每個函式的 CRAP，由高到低列出；任何函式超過門檻，結束碼就是 1，可以直接放進 CI 當品質閘門。

第一次執行時，Go 會自動下載 gocyclo 套件。

## 動手練習

所有指令都在本目錄下執行。

### 練習 1：量測起點

```bash
go run ./tools/crap
```

```
ok      crap    0.998s  coverage: 73.9% of statements
CRAP     C      Cover    Func                     Pos
17.5     14     73.9%    Checkout                 checkout.go:31 ❌

FAIL：1 個函式的 CRAP 超過門檻 12
```

`Checkout` 的圈複雜度是 14，CRAP 17.5，超過門檻。

注意覆蓋率：**只有 2 筆測試，覆蓋率就有 73.9%。** 六條規則裡，VIP 折扣、SAVE100、HALFSHIP、FREESHIP、數量 0 都沒測到，大部分的程式碼卻已經被執行過。覆蓋率算的是「執行過幾行」，不是「測了幾條規則」。

> 💡 動手算算看：C = 14、p = 0.739，代入公式 14² × 0.261³ + 14 ≈ 17.5。

### 練習 2：補測試，碰到天花板

在 `checkout_test.go` 補測試，把六條規則都測到。每個正確答案都要依規格親手算出、寫死（第一課寫答案卷的原則）。

<details>
<summary>參考測試案例（先自己算，再展開對答案）</summary>

```go
{"空購物車", nil, NonMember, "", 0},
{"非會員_500元_加運費100", []Item{{500, 1, false}}, NonMember, "", 600},
{"數量0略過_只算300_加運費100", []Item{{500, 0, false}, {300, 1, false}}, NonMember, "", 400},
{"會員_4000九折3600_滿額折300_免運", []Item{{2000, 2, false}}, Member, "", 3300},
{"VIP_500八五折425_VIP免運", []Item{{500, 1, false}}, VIP, "", 425},
{"會員_特價品不打折", []Item{{1000, 1, true}}, Member, "", 1000},
{"SAVE100_1200折100", []Item{{1200, 1, false}}, NonMember, "SAVE100", 1100},
{"SAVE100_1050折完950_要運費", []Item{{1050, 1, false}}, NonMember, "SAVE100", 1050},
{"HALFSHIP_運費50", []Item{{500, 1, false}}, NonMember, "HALFSHIP", 550},
{"FREESHIP_免運", []Item{{500, 1, false}}, NonMember, "FREESHIP", 500},
```

`SAVE100_1050折完950_要運費` 這筆特別值得記：折完優惠券後金額跌破 1000，反而要付運費。這是兩條規則互相影響的情況。

</details>

補完後再執行一次：

```
ok      crap    0.963s  coverage: 100.0% of statements
CRAP     C      Cover    Func                     Pos
14.0     14     100.0%   Checkout                 checkout.go:31 ❌

FAIL：1 個函式的 CRAP 超過門檻 12
```

覆蓋率已經 100%，CRAP 降到 14 就降不下去了，因為 CRAP 最低只能到 C。**到這一步，補再多測試都沒用，只剩拆函式一條路。**

順便試試放寬門檻：

```bash
go run ./tools/crap -threshold 30
```

會變成 PASS。這就是指南說的「動態門檻」：門檻放寬，同樣的程式就能過關。什麼時候可以放寬、什麼時候要收緊，看的是 AI 代理人有沒有開始出現「改 A 壞 B」的狀況，不是看程式能不能過。

### 練習 3：拆函式

> 開始前請確認練習 2 補的測試都在，而且全綠。這些測試會在你拆函式的時候保護你。

把 `Checkout` 依規則拆成幾個小函式，例如：小計、單項商品金額、折扣率、優惠券、滿額折抵、運費。拆的時候**不要改任何測試**，拆完測試還是全綠，才代表行為沒有被改壞。

<details>
<summary>參考解答（先自己試，再展開）</summary>

```go
// Checkout 計算結帳金額（含運費）。
func Checkout(items []Item, level MemberLevel, coupon string) int {
	if len(items) == 0 {
		return 0
	}
	total := applyThresholdRebate(applyCoupon(subtotal(items, level), coupon))
	return total + shippingFee(total, level, coupon)
}

// subtotal 加總商品金額，數量 <= 0 的商品略過。
func subtotal(items []Item, level MemberLevel) int {
	total := 0
	for _, it := range items {
		if it.Qty <= 0 {
			continue
		}
		total += itemPrice(it, level)
	}
	return total
}

// itemPrice 計算單項商品金額：特價品不打折，其餘依會員等級打折。
func itemPrice(it Item, level MemberLevel) int {
	line := it.Price * it.Qty
	if it.OnSale {
		return line
	}
	return line * discountRate(level) / 100
}

// discountRate 回傳會員等級的折扣百分比。
func discountRate(level MemberLevel) int {
	switch level {
	case Member:
		return 90
	case VIP:
		return 85
	default:
		return 100
	}
}

// applyCoupon 套用 SAVE100：滿 1000 元折 100 元。
func applyCoupon(total int, coupon string) int {
	if coupon == "SAVE100" && total >= 1000 {
		return total - 100
	}
	return total
}

// applyThresholdRebate 滿 3000 元折 300 元。
func applyThresholdRebate(total int) int {
	if total >= 3000 {
		return total - 300
	}
	return total
}

// shippingFee 計算運費。
func shippingFee(total int, level MemberLevel, coupon string) int {
	if total >= 1000 || level == VIP || coupon == "FREESHIP" {
		return 0
	}
	if coupon == "HALFSHIP" {
		return 50
	}
	return 100
}
```

</details>

用參考解答執行的結果（`Pos` 的行號會因你的寫法而不同）：

```
CRAP     C      Cover    Func                     Pos
5.0      5      100.0%   shippingFee              checkout.go:87
3.0      3      100.0%   subtotal                 checkout.go:38
3.0      3      100.0%   discountRate             checkout.go:59
3.0      3      100.0%   applyCoupon              checkout.go:71
2.0      2      100.0%   Checkout                 checkout.go:29
2.0      2      100.0%   itemPrice                checkout.go:50
2.0      2      100.0%   applyThresholdRebate     checkout.go:79

PASS：所有函式的 CRAP 都在門檻 12 以內
```

一個複雜度 14 的函式，拆成七個複雜度 2～5 的小函式。總複雜度沒有變少，但每個函式都小到一眼就能看懂，AI 代理人改其中一個，也比較不會弄壞另一個。

`shippingFee` 的條件是把原本的「未滿 1000 **且**不是 VIP **且**不是 FREESHIP 才收運費」反過來寫成「滿 1000 **或** VIP **或** FREESHIP 就免運」。這種改寫很容易出錯，練習 2 的測試就是用來抓這種錯的。

### 練習 4：CRAP 的弱點

> 先把 `checkout_test.go` 備份起來（例如複製成 `checkout_test.go.bak`），練習完再還原。

把 `checkout_test.go` 的內容換成下面這個**只呼叫、不檢查答案**的測試：

```go
package checkout

import "testing"

// ❌ 只呼叫、不檢查答案的假測試。
func TestCheckout_NoCheck(t *testing.T) {
	Checkout(nil, NonMember, "")
	Checkout([]Item{{500, 0, false}, {300, 1, false}}, NonMember, "")
	Checkout([]Item{{2000, 2, false}}, Member, "")
	Checkout([]Item{{500, 1, false}}, VIP, "")
	Checkout([]Item{{1000, 1, true}}, Member, "")
	Checkout([]Item{{1200, 1, false}}, NonMember, "SAVE100")
	Checkout([]Item{{500, 1, false}}, NonMember, "HALFSHIP")
}
```

執行 `go run ./tools/crap`：覆蓋率 100%，所有函式 PASS，結果跟練習 3 一模一樣。

再把 `discountRate` 裡的 `return 90` 改成 `return 50`（會員打五折），再執行一次：**還是 PASS。**

CRAP 只看「程式碼有沒有被執行過」，不看測試有沒有檢查答案。一個連一行 `t.Errorf` 都沒有的測試，也能把 CRAP 壓到最低。所以：

- CRAP 必須建立在第一課正確的答案卷上才有意義。
- 要抓出這種「執行了但沒在檢查」的測試，要靠第三重約束：變異測試。

練習完記得還原 `checkout_test.go` 和 `discountRate`。

## 學習重點回顧

| 練習 | 你做了什麼 | 學到什麼 |
|---|---|---|
| 1. 量測起點 | 執行 CRAP 工具 | **覆蓋率算的是執行過幾行，不是測了幾條規則。** 2 筆測試就有 73.9%。 |
| 2. 補測試 | 把六條規則都測到 | **CRAP 最低只能到 C。** 覆蓋率 100% 後，複雜度 14 的函式還是過不了門檻 12。 |
| 3. 拆函式 | 把一個大函式拆成七個小函式 | **降低複雜度是唯一的路。** 拆的過程靠第一重約束的測試保護，測試不能動。 |
| 4. 假測試 | 用不檢查答案的測試量 CRAP | **CRAP 分不出真測試和假測試。** 它必須和正確的答案卷一起用，弱點要靠變異測試補上。 |

### 回到 AI 代理人的情境

| 本練習的情況 | 在 AI 代理人開發中的意義 |
|---|---|
| CRAP 超標，結束碼 1 | CI 直接擋下，AI 必須自己拆函式或補測試，不需要人逐行看 |
| 複雜度超過門檻，補測試沒用 | 門檻 12 會逼 AI 把程式寫成小函式，這是用數字取代「請寫乾淨的程式」這種提示詞 |
| 拆函式時測試全綠 | 第一重約束保護第二重約束的重構：AI 拆完函式，測試證明行為沒變 |
| 假測試也能 PASS | AI 為了過 CRAP 門檻，可能寫出只呼叫不檢查的測試，必須靠第三重約束抓出來 |

### 自我檢查

- [ ] 為什麼覆蓋率 100% 時，CRAP 等於圈複雜度？
- [ ] 一個圈複雜度 15 的函式，要怎麼樣才能通過門檻 12？
- [ ] 下面這個函式的圈複雜度是多少？`if a > 0 && b > 0 { ... } else if c == 1 || d == 2 { ... }`
- [ ] 拆函式時，為什麼不能同時修改測試？
- [ ] 練習 4 的假測試讓 CRAP 全部 PASS，你會用什麼方法發現它是假的？

## 延伸

- 補充閱讀：
  - [`補充_圈複雜度.md`](補充_圈複雜度.md)：圈複雜度怎麼算、代表什麼、有哪些盲點
  - [`補充_認知複雜度.md`](補充_認知複雜度.md)：衡量「讀懂程式要花多少腦力」的指標，可以當成 CRAP 之外的另一道閘門
- 下一步：「第三重約束：變異測試」。它會故意把程式改壞（例如把 `return 90` 改成 `return 50`），看測試會不會失敗，正好用來抓出練習 4 的假測試。
- 本工具用的是 Go 的**敘述覆蓋率**（statement coverage）。CRAP 原始定義用的是基本路徑覆蓋率，比敘述覆蓋率嚴格，但多數語言的工具都只提供敘述或分支覆蓋率，實務上一般都直接拿來用。
