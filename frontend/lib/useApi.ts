'use client';

import { useCallback, useEffect, useState } from 'react';
import { errorState, loadingState, successState, type AsyncState } from './api';

/**
 * `lib/api.ts` 함수 하나를 로딩/성공/오류 3-상태로 감싼다.
 *
 * 정적 내보내기라 서버에서 데이터를 못 가져오므로, 데이터가 필요한 화면은
 * 클라이언트 컴포넌트에서 이 훅을 쓴다.
 *
 * ```tsx
 * const crops = useApi(useCallback((opts) => getCrops(opts), []));
 * if (crops.status === 'loading') return <Skeleton.Table rows={3} />;
 * ```
 *
 * `fetcher` 는 렌더마다 새로 만들면 무한 루프가 되니 `useCallback` 으로 고정한다.
 * `fetcher` 가 바뀌어 다시 불러오는 동안에는 직전 데이터가 그대로 보인다 —
 * 화면이 깜빡이지 않게 하려는 것이다. 빈 화면부터 보이려면 `reload()` 를 쓴다.
 */
export function useApi<T>(
  fetcher: (options: { signal: AbortSignal }) => Promise<T>,
): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>(loadingState<T>);
  const [token, setToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    fetcher({ signal: controller.signal })
      .then((data) => {
        if (active) setState(successState(data));
      })
      .catch((error: unknown) => {
        if (active && !controller.signal.aborted) setState(errorState<T>(error));
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [fetcher, token]);

  const reload = useCallback(() => {
    setState(loadingState<T>());
    setToken((value) => value + 1);
  }, []);
  return { ...state, reload };
}
