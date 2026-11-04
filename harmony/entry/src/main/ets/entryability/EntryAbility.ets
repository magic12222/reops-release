import { UIAbility, ConfigurationConstant, Want } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import BuildProfile from 'BuildProfile';
import { TestBootstrap } from '../config/TestBootstrap';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want): void {
    if (BuildProfile.CONTRACT_TEST) {
      const value = want.parameters?.['contractReadToken'];
      if (typeof value === 'string') TestBootstrap.inject(value);
    }
  }
  onWindowStageCreate(stage: window.WindowStage): void {
    try {
      this.context.getApplicationContext().setColorMode(ConfigurationConstant.ColorMode.COLOR_MODE_DARK);
    } catch {
      hilog.warn(0x0000, 'ReOps', 'Unable to set application color mode');
    }
    stage.loadContent('pages/Index', (error) => {
      if (error.code) {
        hilog.error(0x0000, 'ReOps', 'Entry page load failed: %{public}d', error.code);
      }
    });
  }
}
