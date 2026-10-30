import { MotionConfig } from 'motion/react';
import { useEffect } from 'react';
import { t, useLocale } from './i18n';
import { Navbar } from './components/Navbar';
import { Footer } from './components/Footer';
import { PageOutlet } from './pages/PageOutlet';
import { ScrollPosition } from './navigation/ScrollPosition';
import {LiveAnalysisCoordinator} from './workbench/LiveAnalysisCoordinator';

export default function App() {
  const locale = useLocale();
  useEffect(() => {
    document.title = t('ReOps — Failure is a beginning.');
    document.querySelector('meta[name="description"]')?.setAttribute('content',
      t('ReOps — 从故障检测到自主恢复。华为 ICT 创新大赛交互展示原型。'));
  }, [locale]);
  return <MotionConfig reducedMotion="user"><Navbar /><main id="main" tabIndex={-1}><LiveAnalysisCoordinator/><PageOutlet /></main><Footer /><ScrollPosition /></MotionConfig>;
}
