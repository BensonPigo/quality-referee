// Package checkout 計算購物車結帳金額。
//
// 需求規格：
//  1. 購物車是空的，金額為 0
//  2. 數量 <= 0 的商品略過不算
//  3. 非特價商品：會員九折、VIP 八五折；特價商品不再打折
//  4. 優惠券 SAVE100：打折後小計滿 1000 元，再折 100 元
//  5. 折完優惠券後滿 3000 元，再折 300 元
//  6. 運費：小計未滿 1000 元收 100 元；VIP 或優惠券 FREESHIP 免運；優惠券 HALFSHIP 運費 50 元
package checkout

// MemberLevel 會員等級。
type MemberLevel int

const (
	NonMember MemberLevel = iota
	Member
	VIP
)

// Item 購物車中的一項商品。
type Item struct {
	Price  int
	Qty    int
	OnSale bool // 特價商品
}

// Checkout 計算結帳金額（含運費）。
//
// ⚠️ 這是故意寫亂的函式：所有規則都塞在同一個函式裡，圈複雜度 14。
func Checkout(items []Item, level MemberLevel, coupon string) int {
	if len(items) == 0 {
		return 0
	}

	total := 0
	for _, it := range items {
		if it.Qty <= 0 {
			continue
		}
		line := it.Price * it.Qty
		if !it.OnSale {
			if level == Member {
				line = line * 90 / 100
			} else if level == VIP {
				line = line * 85 / 100
			}
		}
		total += line
	}

	if coupon == "SAVE100" && total >= 1000 {
		total -= 100
	}
	if total >= 3000 {
		total -= 300
	}

	shipping := 0
	if total < 1000 && level != VIP && coupon != "FREESHIP" {
		shipping = 100
		if coupon == "HALFSHIP" {
			shipping = 50
		}
	}
	return total + shipping
}
