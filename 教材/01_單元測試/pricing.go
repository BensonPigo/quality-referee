// Package pricing 是「學生作答」：結帳金額「怎麼算」。
//
// 需求規格：
//  1. 小計 = 單價 × 數量
//  2. 會員打九折
//  3. 打折後金額 >= 3000 元，再折 300 元
package pricing

const (
	memberRate      = 90   // 會員折扣百分比（九折）
	threshold       = 3000 // 滿額門檻
	thresholdRebate = 300  // 滿額折抵金額
)

// applyMemberDiscount 套用會員折扣。
func applyMemberDiscount(amount int) int {
	return amount * memberRate / 100
}

// applyThresholdRebate 套用滿額折抵。
func applyThresholdRebate(amount int) int {
	if amount >= threshold {
		return amount - thresholdRebate
	}
	return amount
}

// FinalPrice 計算最終結帳金額：先打會員折扣，再判斷滿額折抵。
func FinalPrice(price, qty int, isMember bool) int {
	subtotal := price * qty
	if isMember {
		subtotal = applyMemberDiscount(subtotal)
	}
	return applyThresholdRebate(subtotal)
}
