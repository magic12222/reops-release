import { t, useLocale } from '../i18n';
import { useId } from 'react';
import { recoveryLabState } from '../data/recoveryLab';

interface PanelProps {
  id: string; x: number; y: number; width: number; height: number; depth: number;
  label: string; role: string; status: string; primary?: boolean;
}

/** Faces are drawn individually: depth is geometry, rather than a card-wide 3D transform. */
function ServicePanel({ id, x, y, width, height, depth, label, role, status, primary }: PanelProps) {
  useLocale();
  return <g className={`lab-node lab-${id} ${primary ? 'primary' : ''}`} transform={`translate(${x} ${y})`}>
    <ellipse className="lab-contact-shadow" cx={width / 2 + depth} cy={height + 15} rx={width / 2 + 20} ry="14" />
    <path className="lab-panel-side" d={`M${width} 0 l${depth} -${depth * .75} v${height} l-${depth} ${depth * .75} Z`} />
    <path className="lab-panel-top" d={`M0 0 l${depth} -${depth * .75} h${width} l-${depth} ${depth * .75} Z`} />
    <rect className="lab-panel-front" width={width} height={height} rx="1" />
    <path className="lab-panel-edge" d={`M1 1 H${width - 1} V${height - 1}`} />
    <g className="lab-service-icon" transform="translate(18 15)">
      {id === 'postgres' ? <><ellipse cx="12" cy="6" rx="11" ry="4.5" /><path d="M1 6v18c0 6 22 6 22 0V6 M1 15c0 6 22 6 22 0" /></>
        : id === 'redis' ? <path d="M1 9l13-7 13 7-13 7Z M1 17l13 7 13-7" />
          : <path d="M1 7h26 M1 15h26" />}
    </g>
    <text className="lab-svc-role" x="56" y="27">{t(role)}</text>
    <text className="lab-svc-name" x="18" y={primary ? 74 : height - 35}>{t(label)}</text>
    <circle className="lab-svc-dot" cx="20" cy={height - 17} r="3" />
    <text className="lab-svc-status" x="31" y={height - 13}>{t(status)}</text>
    {primary && <text className="lab-svc-id" x={width - 18} y={height - 13} textAnchor="end">{t("DB / 01")}</text>}
  </g>;
}

const wide = {
  viewBox: '0 0 1050 400', cx: 554, cy: 230,
  api: { x: 145, y: 208, width: 194, height: 96, depth: 17 },
  postgres: { x: 435, y: 182, width: 238, height: 128, depth: 21 },
  redis: { x: 788, y: 158, width: 174, height: 90, depth: 14 },
  paths: ['M 62 255 H 243', 'M 243 255 H 551', 'M 299 304 V 338 H 874 V 210'],
  floor: 'M 125 308 L 554 361 L 999 263 L 999 292 L 554 398 L 125 339 Z',
  floorTop: 'M 125 308 L 554 361 L 999 263 L 570 212 Z',
};
const compact = {
  viewBox: '0 0 560 500', cx: 278, cy: 267,
  api: { x: 27, y: 129, width: 183, height: 100, depth: 14 },
  postgres: { x: 150, y: 255, width: 249, height: 129, depth: 18 },
  redis: { x: 359, y: 120, width: 174, height: 91, depth: 12 },
  paths: ['M 40 80 V 176 H 90', 'M 116 220 V 319 H 274', 'M 209 192 H 455 V 166'],
  floor: 'M 34 388 L 279 458 L 542 379 L 542 414 L 279 494 L 34 423 Z',
  floorTop: 'M 34 388 L 279 458 L 542 379 L 297 310 Z',
};

function SpatialScene({ index, mobile, prefix }: { index: number; mobile: boolean; prefix: string }) {
  useLocale();
  const state = recoveryLabState(index);
  const layout = mobile ? compact : wide;
  const { cx, cy } = layout;
  const clipId = `${prefix}-${mobile ? 'compact' : 'wide'}`;
  const dbStatus = state.database === 'healthy' ? '健康' : state.database === 'failed' ? '服务停止' : state.database === 'recovering' ? '正在重启' : '等待核验';
  return <svg className={`lab-spatial-svg ${mobile ? 'lab-mobile-scene' : 'lab-desktop-scene'}`} viewBox={layout.viewBox} preserveAspectRatio="xMidYMid meet" role="img" aria-label={t("模拟依赖空间：FastAPI、PostgreSQL、Redis。{0}，业务{1}", t(dbStatus), t(state.request))}>
    <defs><clipPath id={clipId}><path d={layout.floorTop} /></clipPath></defs>
    <g className="lab-camera">
      <g className="lab-foundation" aria-hidden="true">
        <path className="lab-floor-depth" d={layout.floor} />
        <path className="lab-floor-surface" d={layout.floorTop} />
        <g className="lab-floor-grid" clipPath={`url(#${clipId})`}>
          {Array.from({ length: 9 }, (_, i) => <path key={i} d={mobile ? `M${i * 95 - 100} 300l350 180 M0 ${i * 30 + 315}l560 -155` : `M${i * 140 - 200} 200l580 310 M40 ${i * 32 + 260}l1030 -230`} />)}
        </g>
        <path className="lab-floor-rim" d={mobile ? 'M34 388 L279 458 L542 379 M279 458 V494' : 'M125 308 L554 361 L999 263 M554 361 V398'} />
        <g className="lab-position-rings">
          <ellipse cx={cx} cy={cy} rx={mobile ? 225 : 292} ry={mobile ? 168 : 135} />
          <ellipse cx={cx} cy={cy} rx={mobile ? 172 : 228} ry={mobile ? 127 : 105} />
          <ellipse cx={cx} cy={cy} rx={mobile ? 123 : 159} ry={mobile ? 91 : 76} />
          <path d={`M${cx} ${cy - (mobile ? 185 : 150)}v18 M${cx} ${cy + (mobile ? 182 : 146)}v15`} />
        </g>
      </g>
      <g className="lab-spatial-links" aria-hidden="true">
        {layout.paths.map((d, i) => <g key={i} className={`lab-link lab-link-${i} ${index >= 0 && index < 6 && i < 2 ? 'broken' : ''} ${index >= 0 && index < 6 && i === 2 ? 'unused' : ''}`}>
          <path d={d} className="lab-wire" />
          <path d={d} pathLength="100" className="lab-stream" />
          {i < 2 && <path d={d} pathLength="100" className="lab-fault-travel" />}
          {i === 1 && <path d={d} pathLength="100" className="lab-repair-travel" />}
        </g>)}
      </g>
      <g className="lab-probe" transform={mobile ? 'translate(30 40)' : 'translate(90 90)'}>
        <text className="lab-probe-kicker">{t("GET /users")}</text>
        <text className="lab-probe-code" y={mobile ? 36 : 71}>{index < 0 || state.complete ? '200' : index === 6 ? '···' : '503'}</text>
        <text className="lab-probe-detail" y={mobile ? 54 : 94}>{index < 0 ? t('基线响应') : state.complete ? t('业务验证通过') : index === 6 ? t('核验中') : t('业务请求失败')}</text>
      </g>
      <ServicePanel id="redis" {...layout.redis} label="Redis" role="CACHE" status="健康" />
      <ServicePanel id="api" {...layout.api} label="FastAPI" role="APPLICATION" status="进程存活" />
      <g className="lab-root-focus" aria-hidden={!state.focused}>
        <ellipse className="lab-focus-orbit" cx={cx} cy={cy + 21} rx={mobile ? 148 : 157} ry={mobile ? 99 : 96} />
        <path className="lab-focus-bracket" d={mobile ? 'M141 249v-8h286v8' : `M${layout.postgres.x - 9} ${layout.postgres.y - 12}v-18h${layout.postgres.width + 37}v18`} />
        <text className="lab-root-label" x={layout.postgres.x + (mobile ? 75 : 2)} y={mobile ? 234 : layout.postgres.y - 38}>{index >= 3 ? t('ROOT CAUSE / POSTGRESQL') : t('定位数据库依赖')}</text>
      </g>
      <g className="lab-postgres-assembly">
        <ServicePanel id="postgres" {...layout.postgres} label="PostgreSQL" role="DATABASE" status={dbStatus} primary />
      </g>
      <g className="lab-local-feedback" aria-hidden="true">
        <ellipse className="lab-shock" cx={cx} cy={cy + 25} rx="147" ry="94" />
        <ellipse className="lab-restore-ripple" cx={cx} cy={cy + 25} rx="147" ry="94" />
        <ellipse className="lab-execution-orbit" cx={cx} cy={cy + 25} rx="160" ry="107" />
      </g>
      <g className="lab-operation-label" aria-hidden={index !== 5} transform={`translate(${cx} ${mobile ? 70 : 348})`}>
        <text textAnchor="middle">{t("restart_service → postgres")}</text>
      </g>
    </g>
  </svg>;
}

export function RecoveryTopology({ index, moving }: { index: number; moving: boolean }) {
  useLocale();
  const state = recoveryLabState(index);
  const prefix = useId().replace(/:/g, '');
  return <div className={`lab-topology ${moving ? 'is-moving' : 'is-still'} ${state.focused ? 'is-focused' : ''}`} data-step={index} data-database={state.database}>
    <div className="lab-view-heading"><span>{t("服务依赖 / F01")}</span><span className={`lab-system-state ${index >= 0 && index < 6 ? 'degraded' : ''}`}><i />{index < 0 ? t('基线正常') : state.complete ? t('链路恢复') : index === 5 ? t('恢复执行') : index === 6 ? t('等待核验') : t('业务受影响')}</span></div>
    <SpatialScene index={index} mobile={false} prefix={prefix} />
    <SpatialScene index={index} mobile prefix={prefix} />
    <div className="lab-scene-footnote"><span>{t("依赖示意 · 非实时探测")}</span></div>
  </div>;
}
