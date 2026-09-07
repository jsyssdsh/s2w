/** 조건부 className 결합. 뒤에 오는 클래스가 이기는 병합은 하지 않는다 —
 *  컴포넌트가 기본 클래스를 먼저 두고 `className` 을 마지막에 붙인다. */
export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ');
}
