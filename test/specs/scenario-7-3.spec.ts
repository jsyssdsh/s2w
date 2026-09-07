import { expect, test } from '@playwright/test';

/**
 * SPEC 7.3 운영 시나리오 — 휴경농지 및 작물 매칭, 한 줄로 이어서.
 *
 *   토지 소유자: 유휴농지 발생 등록 (위치·면적·용수·임대조건)
 *     → 농가: 재배 조건 입력 (희망작물·면적·예산)
 *     → AI 적합도 분석 (용수·기상·면적·거리·냉장창고)
 *     → 적합도 점수 산출 · 추천 결과 확인
 *     → 매칭 신청 → 스마트팜 재배로 연결 (필지가 운영 중으로 넘어간다)
 *
 * 지도 화면 자체의 검증은 land.spec.ts 가 한다. 여기서 보는 것은 **연결**이다:
 * 방금 등록한 땅이 그대로 추천 후보가 되고, 신청 한 번으로 상태가 넘어가는가.
 *
 * 새 필지는 일부러 조건이 나쁘다(농업용수 미확보 · 예산 초과 임대료 · 3등급
 * 토양). SPEC 5.6 의 A > B > C 순위를 흔들지 않고 맨 뒤에 붙기 위해서다.
 */

const NEW_PARCEL = {
  name: 'E 시험농지',
  areaPyeong: 2400,
  rentManWon: 120,
  soilGrade: '3등급',
  ownerName: '최소유',
};

test('SPEC 7.3 — 유휴농지 등록에서 매칭 신청까지', async ({ page, request }) => {
  const summaryBefore = await (await request.get('/api/parcels/summary')).json();

  await page.goto('/land/');
  await expect(page.getByTestId('parcel-map')).toBeVisible();

  // --- 1) 토지 소유자: 유휴농지 발생 등록 -------------------------------
  await page.getByTestId('register-parcel-open').click();
  const form = page.getByTestId('register-parcel-form');
  await expect(form).toBeVisible();

  await form.getByTestId('register-name').fill(NEW_PARCEL.name);
  await form.getByTestId('register-region').selectOption({ label: '충남 논산시' });
  await form.getByTestId('register-area').fill(String(NEW_PARCEL.areaPyeong));
  await form.getByTestId('register-rent').fill(String(NEW_PARCEL.rentManWon));
  await form.getByTestId('register-soil').selectOption(NEW_PARCEL.soilGrade);
  await form.getByTestId('register-cold').selectOption('none');
  await form.getByTestId('register-owner').fill(NEW_PARCEL.ownerName);
  // 농업용수 미확보 — SPEC 5.6 의 하드 페널티를 그대로 받는다.
  await form.getByTestId('register-water').uncheck();
  await form.getByTestId('register-submit').click();

  // 등록 직후 상태는 유휴다. 필지를 넘기는 것은 매칭 신청뿐이다.
  const success = page.getByTestId('register-success');
  await expect(success).toContainText(NEW_PARCEL.name);
  await expect(success).toContainText('유휴');

  // 지도와 요약 지표가 그 자리에서 갱신된다 (SPEC 4.4).
  const geojson = await (await request.get('/api/parcels/geojson')).json();
  const created = geojson.features.find(
    (feature: { properties: { name: string } }) => feature.properties.name === NEW_PARCEL.name,
  );
  expect(created, '등록한 농지가 지도 데이터에 있어야 한다').toBeTruthy();
  expect(created.properties.status).toBe('idle');

  const parcelId: number = created.properties.id;
  await expect(page.getByTestId(`parcel-marker-${parcelId}`)).toBeVisible();

  const summaryAfter = await (await request.get('/api/parcels/summary')).json();
  expect(summaryAfter.total_count).toBe(summaryBefore.total_count + 1);

  // --- 2) 농가: 재배 조건 입력 → 3) AI 적합도 분석 ---------------------
  // SPEC 5.6 활용 예시 그대로 — 딸기 700~1,000평, 예산 70만 원.
  await page.getByTestId('filter-crop').selectOption({ label: '딸기' });
  await page.getByTestId('filter-area-min').fill('700');
  await page.getByTestId('filter-area-max').fill('1000');
  await page.getByTestId('filter-budget').fill('70');
  await page.getByTestId('compare-submit').click();

  // --- 4) 추천 결과 확인 -------------------------------------------------
  const table = page.getByTestId('compare-table');
  await expect(table).toBeVisible();
  // 방금 등록한 땅이 후보로 들어왔다.
  await expect(page.getByTestId(`compare-head-${parcelId}`)).toHaveText(NEW_PARCEL.name);
  // SPEC 5.6 의 결론은 그대로다 — 용수 없는 새 필지는 A 농지 아래다.
  // (compare-rank-<n> 의 n 은 순위가 아니라 필지 id 다. 1 = A 농지.)
  await expect(page.getByTestId('compare-rank-1')).toHaveText('1위');
  const newRank = await page.getByTestId(`compare-rank-${parcelId}`).innerText();
  expect(Number(newRank.replace('위', ''))).toBeGreaterThan(1);
  // 점수만이 아니라 근거가 함께 나온다 (설명 가능한 추천).
  await expect(page.getByTestId('compare-reasons')).toContainText('농업용수');

  // --- 5) 매칭 신청 → 스마트팜 재배로 연결 ------------------------------
  await page.getByTestId(`apply-${parcelId}`).click();
  const applyForm = page.getByTestId('apply-form');
  await expect(applyForm).toContainText(`${NEW_PARCEL.name} 임대 신청`);
  await applyForm.getByTestId('apply-name').fill('김청년');
  await applyForm.getByTestId('apply-submit').click();

  const applied = page.getByTestId('apply-success');
  await expect(applied).toContainText(NEW_PARCEL.name);
  await expect(applied).toContainText('운영 중');

  // 신청이 필지 상태를 넘겼다 — 더 이상 유휴가 아니므로 신청 버튼이 사라진다.
  await expect(page.getByTestId(`apply-${parcelId}`)).toHaveCount(0);

  const detail = await (await request.get(`/api/parcels/${parcelId}`)).json();
  expect(detail.status).toBe('operating');
  expect(detail.status_label).toBe('운영 중');
  expect(detail.application_count).toBe(1);
  // 등록 때 넣은 소유자가 SPEC 4.5 상세의 연락처로 남는다.
  expect(detail.owner.name).toBe(NEW_PARCEL.ownerName);
});
