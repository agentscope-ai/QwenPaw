export interface CoordinatedPlatformSession {
  accessToken: string;
  expiresAt: number;
}

interface PlatformTokenCoordinatorOptions<
  Session extends CoordinatedPlatformSession,
> {
  earlyRefreshSeconds: number;
  load(): Promise<Session | null>;
  now?: () => number;
  refresh(session: Session): Promise<Session | null>;
}

export class PlatformTokenCoordinator<
  Session extends CoordinatedPlatformSession,
> {
  private refreshPromise: Promise<Session | null> | null = null;
  private readonly now: () => number;

  constructor(
    private readonly options: PlatformTokenCoordinatorOptions<Session>,
  ) {
    this.now = options.now ?? (() => Math.floor(Date.now() / 1000));
  }

  async accessToken(): Promise<string | null> {
    const session = await this.options.load();
    if (!session) return null;
    if (session.expiresAt > this.now() + this.options.earlyRefreshSeconds) {
      return session.accessToken;
    }
    return (await this.refresh(session))?.accessToken ?? null;
  }

  async afterUnauthorized(failedAccessToken: string): Promise<Session | null> {
    const session = await this.options.load();
    if (!session) return null;
    if (session.accessToken !== failedAccessToken) return session;
    return this.refresh(session);
  }

  private refresh(session: Session): Promise<Session | null> {
    if (!this.refreshPromise) {
      this.refreshPromise = this.options.refresh(session).finally(() => {
        this.refreshPromise = null;
      });
    }
    return this.refreshPromise;
  }
}
