// Package checkout 計算購物車結帳金額（第二課練習 3 拆好函式的版本）。
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
