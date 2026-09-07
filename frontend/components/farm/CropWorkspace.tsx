'use client';

import { useCallback, useMemo, useState } from 'react';
import { Button, Card, CardBody, CardHeader, Select } from '@/components/ui';
import {
  createDeal,
  getPriceForecast,
  getShippingWindow,
  getSmartfarmControls,
  getSmartfarmStatus,
  getWholesalerRecommendations,
  type Crop,
  type CropStatus,
  type Deal,
  type Farm,
  type Shipment,
  type Wholesaler,
  type AsyncState,
} from '@/lib/api';
import { useApi } from '@/lib/useApi';
import { addDays, formatDate, formatKg } from '@/lib/format';
import { AiAlertList } from './AiAlertList';
import { CropRegisterPanel } from './CropRegisterPanel';
import { DealHistoryPanel } from './DealHistoryPanel';
import { OverviewCards } from './OverviewCards';
import { PriceAnalysisPanel } from './PriceAnalysisPanel';
import { SmartfarmPanel } from './SmartfarmPanel';
import { WholesalerRecommendationPanel } from './WholesalerRecommendationPanel';

/** SPEC 5.1 활용 예시의 세 후보(기준일 · +2일 · +9일)를 그대로 쓴다. */
const CANDIDATE_OFFSETS = [0, 2, 9];

const QUICK_ACTIONS = [
  { key: 'register', label: '작물 등록' },
  { key: 'recommend', label: 'AI 유통 추천' },
  { key: 'price', label: '가격 분석' },
  { key: 'deals', label: '거래 현황' },
] as const;

type ActionKey = (typeof QUICK_ACTIONS)[number]['key'];

/**
 * 작물 하나를 기준으로 한 농가 대시보드 본문 (SPEC 4.2).
 *
 * 화면의 모든 숫자는 API 응답에서 온다 — 시세는 SPEC 5.1, 도매처 순수익은
 * SPEC 5.2, 재배환경은 SPEC 5.5 의 엔드포인트다.
 */
export function CropWorkspace({
  farm,
  crop,
  crops,
  shipments,
  deals,
  wholesalers,
  onDataChanged,
}: {
  farm: Farm;
  crop: CropStatus;
  crops: Crop[];
  shipments: AsyncState<Shipment[]>;
  deals: AsyncState<Deal[]>;
  wholesalers: AsyncState<Wholesaler[]>;
  /** 출하·거래가 바뀌었으니 다시 읽으라는 신호 */
  onDataChanged: () => void;
}) {
  const [action, setAction] = useState<ActionKey>('recommend');
  const [pickedShipmentId, setPickedShipmentId] = useState<number | null>(null);
  const [pendingWholesalerId, setPendingWholesalerId] = useState<number | null>(null);
  const [dealError, setDealError] = useState<unknown>(null);

  const cropShipments = useMemo(
    () => (shipments.data ?? []).filter((s) => s.crop_id === crop.crop_id),
    [shipments.data, crop.crop_id],
  );
  const shipment =
    cropShipments.find((s) => s.shipment_id === pickedShipmentId) ?? cropShipments[0] ?? null;

  /* --- SPEC 5.1 시세 예측 --- */
  const forecast = useApi(
    useCallback(
      (options) =>
        getPriceForecast({ crop_id: crop.crop_id, region_id: farm.region_id }, options),
      [crop.crop_id, farm.region_id],
    ),
  );

  const baselineDate = shipment?.ship_date ?? forecast.data?.as_of ?? null;
  const windowQty = shipment?.qty_kg ?? crop.expected_yield_kg;

  const shippingWindow = useApi(
    useCallback(
      (options) => {
        if (!baselineDate) return new Promise<never>(() => {});
        return getShippingWindow(
          {
            crop_id: crop.crop_id,
            region_id: farm.region_id,
            qty_kg: windowQty,
            candidate_dates: CANDIDATE_OFFSETS.map((offset) => addDays(baselineDate, offset)),
          },
          options,
        );
      },
      [baselineDate, crop.crop_id, farm.region_id, windowQty],
    ),
  );

  /* --- SPEC 5.2 도매처 추천 --- */
  const recommendation = useApi(
    useCallback(
      (options) => {
        if (!shipment) return new Promise<never>(() => {});
        return getWholesalerRecommendations(
          {
            farm_id: farm.farm_id,
            crop_id: shipment.crop_id,
            qty_kg: shipment.qty_kg,
            ship_date: shipment.ship_date,
          },
          options,
        );
      },
      [farm.farm_id, shipment],
    ),
  );

  /* --- SPEC 5.5 스마트팜 --- */
  const smartfarm = useApi(
    useCallback(
      (options) => getSmartfarmStatus(crop.smartfarm_id, options),
      [crop.smartfarm_id],
    ),
  );
  const controls = useApi(
    useCallback(
      (options) => getSmartfarmControls(crop.smartfarm_id, 5, options),
      [crop.smartfarm_id],
    ),
  );

  const chosenWholesalerId =
    shipment?.deals.find((deal) => deal.status === 'accepted' || deal.status === 'settled')
      ?.wholesaler_id ?? null;

  async function chooseWholesaler(wholesalerId: number) {
    if (!shipment || pendingWholesalerId !== null) return;
    setPendingWholesalerId(wholesalerId);
    setDealError(null);
    try {
      await createDeal({
        shipment_id: shipment.shipment_id,
        wholesaler_id: wholesalerId,
        status: 'accepted',
      });
      onDataChanged();
      setAction('deals');
    } catch (cause) {
      setDealError(cause);
    } finally {
      setPendingWholesalerId(null);
    }
  }

  return (
    <div className="space-y-6">
      <OverviewCards
        crop={crop}
        forecast={forecast}
        recommendation={recommendation}
        hasShipment={shipment !== null}
      />

      <AiAlertList
        shippingWindow={shippingWindow}
        recommendation={recommendation}
        smartfarm={smartfarm}
        controls={controls}
      />

      <Card>
        <CardHeader
          title="빠른 기능"
          description="작물 등록 · AI 유통 추천 · 가격 분석 · 거래 현황"
          action={
            cropShipments.length > 1 ? (
              <Select
                id="shipment-picker"
                label="기준 출하"
                value={String(shipment?.shipment_id ?? '')}
                onChange={(event) => setPickedShipmentId(Number(event.target.value))}
                options={cropShipments.map((s) => ({
                  value: String(s.shipment_id),
                  label: `${formatDate(s.ship_date)} · ${formatKg(s.qty_kg)}`,
                }))}
              />
            ) : undefined
          }
        />
        <CardBody>
          <div
            role="tablist"
            aria-label="빠른 기능"
            data-testid="quick-actions"
            className="grid grid-cols-2 gap-2 sm:grid-cols-4"
          >
            {QUICK_ACTIONS.map((item) => (
              <Button
                key={item.key}
                role="tab"
                id={`quick-action-${item.key}`}
                aria-selected={action === item.key}
                aria-controls={`quick-panel-${item.key}`}
                variant={action === item.key ? 'primary' : 'secondary'}
                onClick={() => setAction(item.key)}
              >
                {item.label}
              </Button>
            ))}
          </div>
        </CardBody>
      </Card>

      <div
        role="tabpanel"
        id={`quick-panel-${action}`}
        aria-labelledby={`quick-action-${action}`}
      >
        {action === 'register' ? (
          <CropRegisterPanel
            farm={farm}
            crops={crops}
            defaultShipDate={baselineDate ?? ''}
            onCreated={(created) => {
              setPickedShipmentId(created.shipment_id);
              onDataChanged();
              setAction('recommend');
            }}
          />
        ) : null}

        {action === 'recommend' ? (
          <WholesalerRecommendationPanel
            shipment={shipment}
            recommendation={recommendation}
            selectedWholesalerId={chosenWholesalerId}
            pendingWholesalerId={pendingWholesalerId}
            dealError={dealError}
            onSelect={chooseWholesaler}
          />
        ) : null}

        {action === 'price' ? (
          <PriceAnalysisPanel forecast={forecast} shippingWindow={shippingWindow} />
        ) : null}

        {action === 'deals' ? (
          <DealHistoryPanel deals={deals} shipments={shipments} wholesalers={wholesalers} />
        ) : null}
      </div>

      <SmartfarmPanel status={smartfarm} />
    </div>
  );
}
