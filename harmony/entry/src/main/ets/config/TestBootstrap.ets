// Only used by the CONTRACT_TEST build at ability creation. No real credential,
// endpoint or launch parameter is accepted by the default product.
export class TestBootstrap {
  private static value: string = '';
  static inject(value: string): void { TestBootstrap.value = value; }
  static take(): string { const value = TestBootstrap.value; TestBootstrap.value = ''; return value; }
}
